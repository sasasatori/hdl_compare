#!/usr/bin/env python3
"""汇总 results/<lang>/<case>.json -> results/report.md (markdown 评估报告).

评分 (每案例): 功能 60% (cocotb 通过率) + 面积 20% (最优面积/本面积) + 时序 20% (本Fmax/最优Fmax).
功耗列仅参考: OpenSTA 在无寄生参数下的名义功耗, 绝对值失真, 只做同库相对比较.
"""
import glob
import json
import os
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RESULTS = os.path.join(ROOT, "results")
LANGS = ["systemverilog", "chisel", "spade"]
CASES = ["fifo", "uart", "fir", "matmul", "i2c_master"]


def load():
    data = {}  # (lang, case) -> json
    for lang in LANGS:
        for f in glob.glob(os.path.join(RESULTS, lang, "*.json")):
            d = json.load(open(f))
            data[(lang, d["case"])] = d
    return data


def case_score(d, best_area, best_crit, best_power):
    sim = d.get("sim", {})
    func = sim.get("pass", 0) / sim.get("total", 1) if sim.get("total") else 0.0
    sy = d.get("synth", {})
    area_s = (best_area / sy["area_um2"]) if sy.get("area_um2") and best_area else 0.0
    time_s = (best_crit / sy["crit_ns"]) if sy.get("crit_ns") and best_crit else 0.0
    power_s = (best_power / sy["power_w"]) if sy.get("power_w") and best_power else 0.0
    total = 0.4 * func + 0.2 * area_s + 0.2 * time_s + 0.2 * power_s
    return func, area_s, time_s, power_s, total


def main():
    data = load()
    lines = []
    add = lines.append
    add("# HDL 对比评估报告")
    add(f"\n生成时间: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
    add("评分: 功能 40% + 面积 20% + 时序 20% + 功耗 20% (各项均按同案例三语言最优值归一化; 功耗为 OpenSTA 统一翻转率 0.1@100MHz 名义值)\n")

    summary = {l: [] for l in LANGS}
    for case in CASES:
        rows = [(l, data.get((l, case))) for l in LANGS]
        present = [(l, d) for l, d in rows if d]
        if not present:
            continue
        best_area = min((d["synth"].get("area_um2") for _, d in present if d.get("synth", {}).get("area_um2")), default=None)
        best_crit = min((d["synth"].get("crit_ns") for _, d in present if d.get("synth", {}).get("crit_ns")), default=None)
        best_power = min((d["synth"].get("power_w") for _, d in present if d.get("synth", {}).get("power_w")), default=None)
        add(f"\n## 案例 `{case}`\n")
        add("| 语言 | 功能 | 面积 µm² | 单元数 | 关键路径 ns | Fmax MHz | 功耗 W* | LOC | 综合得分 |")
        add("|---|---|---|---|---|---|---|---|---|")
        for lang, d in rows:
            if not d:
                add(f"| {lang} | — 未提交 — | | | | | | | 0 |")
                continue
            sim, sy, loc = d.get("sim", {}), d.get("synth", {}), d.get("loc", {})
            func, area_s, time_s, power_s, total = case_score(d, best_area, best_crit, best_power)
            summary[lang].append(total)
            fail_names = ", ".join(t["name"].replace("test_", "") for t in sim.get("tests", []) if not t["passed"])
            func_s = f"{sim.get('pass', 0)}/{sim.get('total', 0)}" + (f" ✗{fail_names}" if fail_names else "")
            add(f"| {lang} | {func_s} | {sy.get('area_um2', '—')} | {sy.get('cells', '—')} | "
                f"{sy.get('crit_ns', '—')} | {sy.get('fmax_mhz', '—')} | {sy.get('power_w', '—')} | "
                f"{loc.get('lines', '—')} | {total:.3f} |")

    # 代理耗时 (results/agent_time.json, 可选)
    time_file = os.path.join(RESULTS, "agent_time.json")
    agent_time = {}
    if os.path.exists(time_file):
        agent_time = {k: v for k, v in json.load(open(time_file)).items() if not k.startswith("_")}

    add("\n## 总结\n")
    add("| 语言 | 平均综合得分 | 完成功能率 | 总 LOC | 代理耗时 |")
    add("|---|---|---|---|---|")
    for lang in LANGS:
        t_human = agent_time.get(lang, {}).get("human", "—")
        scores = summary[lang]
        if not scores:
            add(f"| {lang} | 0 | 0/0 | 0 | {t_human} |")
            continue
        total_func_p = sum(data[(lang, c)].get("sim", {}).get("pass", 0) for c in CASES if (lang, c) in data)
        total_func_t = sum(data[(lang, c)].get("sim", {}).get("total", 0) for c in CASES if (lang, c) in data)
        total_loc = sum(data[(lang, c)].get("loc", {}).get("lines", 0) for c in CASES if (lang, c) in data)
        add(f"| {lang} | {sum(scores)/len(CASES):.3f} | {total_func_p}/{total_func_t} | {total_loc} | {t_human} |")
    add("\n\\* 功耗为 OpenSTA 名义值 (sky130 tt_025C_1v80, 100MHz, 统一翻转率 0.1), 仅横向相对比较; 绝对值不等于实测功耗.\n")

    out = os.path.join(RESULTS, "report.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[REPORT] -> {out}")
    # 控制台摘要
    for line in lines[-(len(LANGS) + 6):]:
        print(line)


if __name__ == "__main__":
    main()
