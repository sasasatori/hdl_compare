#!/usr/bin/env python3
"""统一评估 runner: python3 run_case.py <lang> <case> [选项]

流程: build (各语言工具链产出 Verilog) -> cocotb 仿真 -> sv2v+yosys 综合 -> results/<lang>/<case>.json
详见 suite/RULES.md。
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

SUITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # suite/
ROOT = os.path.dirname(SUITE)
TB_DIR = os.path.join(SUITE, "common", "tb")

CASES = {  # case -> 顶层模块名
    "fifo": "sync_fifo",
    "uart": "uart_trx",
    "fir": "fir16",
    "matmul": "matmul4x4",
    "i2c_master": "i2c_master",
}
LANGS = ["systemverilog", "systemverilog_v2", "chisel", "spade", "spinal"]

LIBERTY = os.path.join(
    os.environ.get("PDK_ROOT", "/fact_home/yiyangyuan/tools/pdk/ciel/sky130/versions/0fe599b2afb6708d281543108caf8310912f54af"),
    "sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")


def sh(cmd, cwd=None, timeout=1200, log=None):
    """跑命令, 返回 (rc, stdout+stderr). 输出同时写 log 文件."""
    p = subprocess.run(cmd, cwd=cwd, timeout=timeout, shell=isinstance(cmd, str),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = p.stdout or ""
    if log:
        with open(log, "a") as f:
            f.write(f"\n$ {' '.join(cmd) if isinstance(cmd, list) else cmd}\n{out}\n")
    return p.returncode, out


def find_rtl(lang, case, impl_dir):
    """返回 (verilog 源文件列表, build 日志字符串). 可能触发 build."""
    build_log = ""
    if lang in ("systemverilog", "systemverilog_v2"):
        files = []
        if lang == "systemverilog_v2":
            # SVP 原语库 (共享, 先于案例源)
            files += sorted(glob.glob(os.path.join(ROOT, "impl", lang, "lib", "*.sv")))
        files += sorted(glob.glob(os.path.join(impl_dir, "src", "*.sv"))
                        + glob.glob(os.path.join(impl_dir, "src", "*.v")))
        if not files:
            raise RuntimeError(f"未找到源文件: {impl_dir}/src/*.sv")
        return files, build_log

    if lang in ("chisel", "spinal"):
        rc, out = sh(["scala-cli", "run", "."], cwd=impl_dir, timeout=1800)
        build_log += out
        if rc != 0:
            raise RuntimeError(f"{lang} 生成失败 (rc={rc})")
        files = sorted(glob.glob(os.path.join(impl_dir, "build", "*.sv"))
                       + glob.glob(os.path.join(impl_dir, "build", "*.v")))
        if not files:
            raise RuntimeError(f"{lang} 未产出 build/*.sv|*.v")
        return files, build_log

    if lang == "spade":
        rc, out = sh(["swim", "build"], cwd=impl_dir, timeout=1800)
        build_log += out
        if rc != 0:
            raise RuntimeError(f"swim build 失败 (rc={rc})")
        core = os.path.join(impl_dir, "build", "spade.sv")
        if not os.path.exists(core):
            raise RuntimeError("swim 未产出 build/spade.sv")
        wrappers = sorted(glob.glob(os.path.join(impl_dir, "src", "*.v")))
        return [core] + wrappers, build_log  # wrapper(若有) 排最后, 顶层在其中

    raise ValueError(lang)


def run_sim(lang, case, top, sources, workdir, sim="verilator", seed=42, waves=False, log=None):
    """cocotb 仿真. 返回 dict."""
    from cocotb_tools.runner import get_runner
    runner = get_runner(sim)
    os.makedirs(workdir, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = TB_DIR + os.pathsep + env.get("PYTHONPATH", "")

    build_args, test_args = [], []
    if sim == "verilator":
        build_args = ["--timescale-override", "1ns/1ps", "-Wno-DECLFILENAME", "-Wno-fatal"]
    elif sim == "icarus":
        build_args = ["-g2012"]

    t0 = time.time()
    res = {"sim": sim, "ok": False}
    try:
        runner.build(
            sources=sources,
            hdl_toplevel=top,
            build_dir=workdir,
            build_args=build_args,
            always=True,
            waves=waves,
        )
    except Exception as e:
        res["error"] = f"仿真编译失败: {e}"
        return res

    xml_path = os.path.join(workdir, "results.xml")
    try:
        runner.test(
            hdl_toplevel=top,
            test_module=f"tb_{case}",
            test_dir=TB_DIR,
            build_dir=workdir,
            results_xml=xml_path,
            seed=seed,
            extra_env=env,
        )
    except Exception as e:
        res["error"] = f"仿真运行异常: {e}\n{traceback.format_exc()[-2000:]}"
        return res
    res["duration_s"] = round(time.time() - t0, 1)

    tests = []
    if os.path.exists(xml_path):
        tree = ET.parse(xml_path)
        for ts in tree.getroot().iter("testsuite"):
            for tc in ts.iter("testcase"):
                name = tc.get("name")
                fail_el = tc.find("failure")
                if fail_el is None:
                    fail_el = tc.find("error")
                msg = ""
                if fail_el is not None:
                    msg = (fail_el.get("error_msg") or fail_el.get("message")
                           or (fail_el.text or ""))[:300]
                tests.append({"name": name, "passed": fail_el is None, "msg": msg})
    res["tests"] = tests
    res["pass"] = sum(1 for t in tests if t["passed"])
    res["total"] = len(tests)
    res["ok"] = bool(tests) and res["pass"] == res["total"]
    return res


def run_synth(top, sources, workdir, log=None):
    """sv2v -> yosys(映射 sky130) -> OpenSTA(时序+功耗). 返回 dict."""
    os.makedirs(workdir, exist_ok=True)
    combined = os.path.join(workdir, "combined.v")
    res = {"ok": False}

    # sv2v 统一转换 (.v 原样透传)
    sv_files = [s for s in sources if s.endswith(".sv")]
    v_files = [s for s in sources if s.endswith(".v")]
    parts = []
    if sv_files:
        rc, out = sh(["sv2v"] + sv_files, log=log)
        if rc != 0:
            res["error"] = f"sv2v 失败:\n{out[-2000:]}"
            return res
        parts.append(out)
    for vf in v_files:
        with open(vf) as f:
            parts.append(f.read())
    with open(combined, "w") as f:
        f.write("\n".join(parts))

    mapped = os.path.join(workdir, "mapped.v")
    ys = f"""
read_verilog {combined}
hierarchy -check -top {top}
proc
tee -o {workdir}/stat_proc.txt stat
opt
fsm; opt
memory; opt
techmap; opt
flatten
dfflibmap -liberty {LIBERTY}
abc -liberty {LIBERTY} -dff
opt_clean -purge
tee -o {workdir}/stat.txt stat -liberty {LIBERTY}
write_verilog -noattr -noexpr {mapped}
""".strip()
    ys_path = os.path.join(workdir, "synth.ys")
    with open(ys_path, "w") as f:
        f.write(ys + "\n")
    rc, out = sh(["yosys", "-Q", "-T", ys_path], timeout=1200, log=log)
    with open(os.path.join(workdir, "yosys.log"), "w") as f:
        f.write(out)
    if rc != 0:
        res["error"] = f"yosys 失败 (rc={rc}), 见 yosys.log"
        return res

    with open(os.path.join(workdir, "stat_proc.txt")) as f:
        proc_stat = f.read()
    res["has_latch"] = bool(re.search(r"\$_?dlatch|\$_?sr\b", proc_stat, re.I))
    # OpenSTA 的 Verilog 子集不接受 `wire signed`: 剥离 signed (不影响结构/时序)
    with open(mapped) as f:
        mv = f.read()
    if "wire signed" in mv:
        with open(mapped, "w") as f:
            f.write(mv.replace("wire signed", "wire"))

    m = re.search(r"Chip area for module '\\?" + re.escape(top) + r"':\s*([0-9.]+)", out)
    if not m:
        m = re.search(r"Chip area for (?:module|top module) .*?:\s*([0-9.]+)", out)
    res["area_um2"] = float(m.group(1)) if m else None
    m = re.search(r"Number of cells:\s+(\d+)", out)
    if not m:  # 层级树格式: "316 5.37E+03 cells"
        m = re.search(r"^\s+(\d+)\s+\S+\s+cells$", out, re.M)
    res["cells"] = int(m.group(1)) if m else None

    # OpenSTA: 关键路径 (report_clock_min_period) + 功耗 (统一翻转率 0.1 @100MHz)
    res.update(run_sta(top, mapped, workdir, log))
    res["ok"] = res["area_um2"] is not None and res.get("crit_ns") is not None
    return res


def run_sta(top, mapped, workdir, log=None):
    """OpenSTA: report_clock_min_period + report_power (统一翻转率 0.1@100MHz, 避免默认活动标注伪影).
    返回 dict 补丁: crit_ns/fmax_mhz/power_w/sta_rc."""
    tcl_lines = [
        f"read_liberty {LIBERTY}",
        f"read_verilog {mapped}",
        f"link_design {top}",
        "create_clock -name core_clk -period 10.0 [get_ports clk]",
        "catch { set_false_path -from [get_ports rst] }",
        "set_power_activity -global -activity 0.1",
        "report_clock_min_period",
        "report_power",
    ]
    sta_tcl = os.path.join(workdir, "sta.tcl")
    with open(sta_tcl, "w") as f:
        f.write("\n".join(tcl_lines) + "\n")
    sif = os.environ.get("LIBRELANE_SIF", "/fact_home/yiyangyuan/tools/singularity-images/librelane-2.4.2.sif")
    rc2, sta_out = sh(["singularity", "exec", sif, "sta", "-no_init", "-exit", sta_tcl],
                      timeout=600, log=log)
    with open(os.path.join(workdir, "sta.log"), "w") as f:
        f.write(sta_out)
    patch = {"sta_rc": rc2}
    m = re.search(r"period_min\s*=\s*([0-9.]+)\s+fmax\s*=\s*([0-9.]+)", sta_out)
    if m:
        patch["crit_ns"] = float(m.group(1))
        patch["fmax_mhz"] = float(m.group(2))
    m = re.search(r"^Total\s+(?:\S+\s+){3}(\S+)", sta_out, re.M)
    if m:
        patch["power_w"] = float(m.group(1))
    return patch


def count_loc(lang, impl_dir):
    pats = {"systemverilog": ["src/*.sv", "src/*.v"],
            "systemverilog_v2": ["src/*.sv", "src/*.v"],
            "chisel": ["**/*.scala"],
            "spinal": ["**/*.scala"],
            "spade": ["src/*.spade", "src/*.v"]}[lang]
    total, files = 0, 0
    for pat in pats:
        for f in glob.glob(os.path.join(impl_dir, pat), recursive=True):
            if "target" in f or ".scala-build" in f or "/build/" in f:
                continue
            with open(f, errors="ignore") as fh:
                n = sum(1 for line in fh if line.strip() and not line.strip().startswith("//"))
            total += n
            files += 1
    return {"lines": total, "files": files}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lang", choices=LANGS)
    ap.add_argument("case", choices=sorted(CASES))
    ap.add_argument("--sim", default="verilator", choices=["verilator", "icarus"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-sim", action="store_true")
    ap.add_argument("--skip-synth", action="store_true")
    ap.add_argument("--waves", action="store_true")
    ap.add_argument("--only-power", action="store_true",
                    help="只重算功耗/时序: 复用既有 mapped.v + 现有 json, 不重跑 build/sim/synth")
    args = ap.parse_args()


    top = CASES[args.case]
    impl_dir = os.path.join(ROOT, "impl", args.lang, args.case)
    if not os.path.isdir(impl_dir):
        # validation 参考实现走同一 harness (仅供套件自检)
        impl_dir = os.path.join(SUITE, "validation", args.lang, args.case)
    if not os.path.isdir(impl_dir):
        print(f"[FAIL] 实现目录不存在: {impl_dir}", flush=True)
        sys.exit(2)

    res_dir = os.path.join(ROOT, "results", args.lang, args.case)
    os.makedirs(res_dir, exist_ok=True)
    log_file = os.path.join(res_dir, "run.log")
    if os.path.exists(log_file):
        os.remove(log_file)

    result = {
        "lang": args.lang, "case": args.case, "top": top,
        "seed": args.seed,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    t0 = time.time()

    if args.only_power:
        json_path = _json_path(args)
        mapped = os.path.join(res_dir, "synth", "mapped.v")
        if not os.path.exists(json_path) or not os.path.exists(mapped):
            print(f"[FAIL] --only-power 需要既有 {json_path} 与 {mapped}", flush=True)
            sys.exit(2)
        result = json.load(open(json_path))
        patch = run_sta(top, mapped, os.path.join(res_dir, "synth"), log=log_file)
        result.setdefault("synth", {}).update(patch)
        result["synth"]["power_model"] = "opensta_uniform_activity_0.1@100MHz"
        result["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(json_path, "w") as f:
            json.dump(result, f, indent=1, ensure_ascii=False)
        print(f"[POWER] {args.lang}/{args.case}: power={patch.get('power_w')} W, "
              f"crit={patch.get('crit_ns')} ns -> {json_path}", flush=True)
        sys.exit(0 if "power_w" in patch else 1)

    # 1. build / 收集 RTL
    try:
        sources, build_log = find_rtl(args.lang, args.case, impl_dir)
        result["build"] = {"ok": True, "sources": [os.path.relpath(s, ROOT) for s in sources]}
        if build_log:
            with open(log_file, "a") as f:
                f.write(build_log)
    except Exception as e:
        result["build"] = {"ok": False, "error": str(e)}
        _emit(result, res_dir, t0)
        print(f"[FAIL] build: {e}", flush=True)
        sys.exit(1)

    # 2. 仿真
    if not args.skip_sim:
        sim_res = run_sim(args.lang, args.case, top, sources,
                          os.path.join(res_dir, "sim"), sim=args.sim,
                          seed=args.seed, waves=args.waves, log=log_file)
        result["sim"] = sim_res
        status = f"{sim_res.get('pass', 0)}/{sim_res.get('total', 0)}"
        print(f"[SIM] {args.lang}/{args.case}: {status} 通过", flush=True)

        if "error" in sim_res:
            print(f"[SIM ERROR] {sim_res['error'][:500]}", flush=True)

    # 3. 综合
    if not args.skip_synth:
        synth_res = run_synth(top, sources, os.path.join(res_dir, "synth"), log=log_file)
        result["synth"] = synth_res
        if synth_res.get("ok"):
            print(f"[SYNTH] area={synth_res['area_um2']} um2, cells={synth_res['cells']}, "
                  f"crit={synth_res.get('crit_ns')} ns, fmax={synth_res.get('fmax_mhz')} MHz, "
                  f"power={synth_res.get('power_w')} W", flush=True)
        else:
            print(f"[SYNTH FAIL] {synth_res.get('error', '')[:500]}", flush=True)

    result["loc"] = count_loc(args.lang, impl_dir)
    _emit(result, res_dir, t0)
    print(f"[DONE] -> {os.path.join(res_dir, os.path.basename(_json_path(args)))}", flush=True)


def _json_path(args):
    return os.path.join(ROOT, "results", args.lang, f"{args.case}.json")


def _emit(result, res_dir, t0):
    result["elapsed_s"] = round(time.time() - t0, 1)
    # 主 json 放 results/<lang>/<case>.json, 详目在 results/<lang>/<case>/ 下
    class _A:  # 避免再传 args
        pass
    a = _A(); a.lang = result["lang"]; a.case = result["case"]
    with open(_json_path(a), "w") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
