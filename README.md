# hdl_compare — SystemVerilog / Chisel / Spade 的 Agent 适用性对比

## 目标

用一套**统一、盲评、可复现**的设计-验证-评估套件，比较三种 HDL 在 agent 驱动开发下的：
功能正确率、交付质量（PPA）、以及开发摩擦（工具链/语言坑）。

## 结构

```
hdl_compare/
├── env.sh                        # 套件环境 (先 source 它)
├── suite/                        # 评估套件 (代理只读, 禁止修改)
│   ├── RULES.md                  # 实现规则与交付契约 ★代理必读
│   ├── cases/<case>/SPEC.md      # 5 个案例的设计要求 (功能/端口/时序/性能/测试点)
│   ├── common/
│   │   ├── tb/                   # 统一 cocotb 2.0 测试 (python 参考模型, 固定种子)
│   │   ├── harness/run_case.py   # 统一评估入口: build -> sim -> synth(PPA) -> json
│   │   ├── harness/report.py     # 汇总 results/ -> results/report.md
│   │   └── templates/{systemverilog,chisel,spade}/  # 各语言工程模板
│   └── validation/               # 参考实现 (套件自检用, 代理禁止查看)
├── impl/{systemverilog,chisel,spade}/   # 三个代理的工作区 (互相隔离)
└── results/                      # 每语言每案例的 json + report.md
```

## 案例

| 案例 | 顶层 | 难度 | 考察 |
|---|---|---|---|
| fifo | `sync_fifo` | ★ | 指针/存储、边界、ready/valid |
| uart | `uart_trx` | ★★ | FSM、波特率、过采样、位级时序 |
| fir | `fir16` | ★★★ | 定点乘加、流水线、舍入饱和、背压 |
| matmul | `matmul4x4` | ★★★ | 二维阵列、累加、流协议 |
| i2c_master | `i2c_master` | ★★★★ | 复杂 FSM、开漏总线、时钟延展 |

## 运行

```bash
source env.sh
python3 suite/common/harness/run_case.py <lang> <case>     # 完整评估 (build+sim+synth)
python3 suite/common/harness/report.py                     # 生成 results/report.md
```

- 仿真: cocotb 2.0.1 + Verilator 5.050（备选 iverilog: `--sim icarus`）
- PPA: sv2v → Yosys 0.67 (sky130_fd_sc_hd, tt_025C_1v80) → 面积/单元数；
  OpenSTA 2.6 (LibreLane 容器) → `report_clock_min_period` 关键路径/Fmax + 名义功耗。
- 判分只认 harness 输出；测试平台固定种子、含协议监视器与 Python 位精确参考模型。

## Phase 2（三代理盲评）要点

1. 三个代理分别只拿到：本 README + `suite/RULES.md` + `suite/cases/*/SPEC.md` + 对应语言模板；
   **互相看不到** `impl/` 下彼此的目录；不得读 `suite/validation/`。
2. 每个代理在自己的工作区完成全部 5 个案例，用 `run_case.py` 自测到全绿（或尽力）。
3. 结束后 `report.py` 汇总：功能通过率 + 面积/时序/功耗 + LOC 对比。

## 环境依赖

全部在 `~/tools`（免 sudo）；新增组件已登记进 `~/tools/README.md`。
重负载走 `sbatch -p eda`（本套件的 harness 运行为轻负载，登录节点可直接跑）。
