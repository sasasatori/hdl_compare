# 实现规则与交付契约

本文档对三种语言的实现代理具有**约束力**。任何偏离契约的实现将在评估中直接判 0 分。

## 1. 全局设计条件

1. **时钟与复位**：所有设计单时钟 `clk`（上升沿有效），高电平有效复位 `rst`；测试只检查“`rst=1` 保持至少一个时钟沿之后”的状态，实现可选同步或异步高有效复位（Spade 的 `reg ... reset` 为同步高有效）。
   - 复位后所有状态寄存器必须处于 SPEC 规定的初值；
   - 禁止 `initial` 块赋状态初值。
2. **可综合性**：只允许可综合子集。禁止 `#delay`、`fork/join`、`while` 无界循环、锁存器（不允许推断出 latch）、三态 `inout`（开漏总线用 `_o/_i` 分离建模，见 i2c 案例）。
3. **端口契约**：顶层模块名、端口名、位宽、方向必须与对应案例 `suite/cases/<case>/SPEC.md` **完全一致**。不允许增加/删除端口，不允许使用 interface/struct/unpacked array 端口（端口只能是 1bit 或 packed 向量）。
4. **黑盒性**：DUT 不得引用、探测或依赖测试平台内部信号；不得用 `$display`/`$error` 假装通过测试；不得包含仅用于通过测试的特例逻辑（如匹配测试向量的硬编码输出）。
5. **随机性**：测试用固定种子驱动，DUT 必须为确定性逻辑。

## 2. 目录与交付物

每种语言一个工作区，代理只准在自己的工作区内工作：

```
impl/
├── systemverilog/<case>/     # SystemVerilog 代理
├── chisel/<case>/            # Chisel 代理
└── spade/<case>/             # Spade 代理
```

**绝对禁止**：修改 `suite/` 下任何文件；读取其他语言工作区的任何文件（含 git 历史）。

### 2.1 SystemVerilog 交付

- 源文件置于 `impl/systemverilog/<case>/src/`，可多个 `.sv`/`.v` 文件；
- 顶层模块名 = SPEC 规定（如 `sync_fifo`）；
- harness 将直接把这些文件交给 Verilator 仿真、经 sv2v 转换后交给 Yosys 综合。

### 2.2 Chisel 交付

- 在 `impl/chisel/<case>/` 下建立 scala-cli 工程（模板见 `suite/common/templates/chisel/`，Chisel/Scala 版本由模板固定，不得更改）；
- 工程必须恰好含一个 main object，评估命令为：
  ```
  cd impl/chisel/<case> && scala-cli run .
  ```
  该命令必须重新生成 `impl/chisel/<case>/build/<top>.sv`（`--target-dir build`，顶层模块名 = SPEC 规定名）；
- 用 `RawModule` + 具名 `clk`/`rst` 端口 + `withClockAndReset`（同步高有效 `Bool` 复位），保证端口契约；生成代码必须可被 Verilator 仿真；生成代码中的 `$fatal`/`assert` 如可能在合法输入下触发须关闭（firtool 加 `--disable-all-randomization` 已由模板处理）。

### 2.3 Spade 交付

- 在 `impl/spade/<case>/` 下建立 swim 工程（模板见 `suite/common/templates/spade/`）；
- 评估命令为：
  ```
  cd impl/spade/<case> && swim build
  ```
  该命令必须生成 `impl/spade/<case>/build/spade.sv`；
  - swim.toml 的 `name` 必须等于案例目录名（如 `fifo`），顶层实体名必须为 `<top>_impl`（如 `sync_fifo_impl`）；Spade 生成的模块名为 `<name>::<entity>`，形如 `fifo::sync_fifo_impl`；

## 3. 评估命令（代理的自测入口）

一切自测都必须通过以下统一入口（登录节点可直接运行，负载很小）：

```bash
cd /fact_home/yiyangyuan/workspace/projects/hdl_compare
source env.sh
python3 suite/common/harness/run_case.py <lang> <case>          # 完整: build+sim+synth
python3 suite/common/harness/run_case.py <lang> <case> --skip-synth   # 只仿真
python3 suite/common/harness/run_case.py <lang> <case> --sim icarus   # 换仿真器(调试用)
```

- 输出：`results/<lang>/<case>.json`，含 build/sim/synth 全部结果；
- 仿真日志、波形（`WAVES=1` 时）在 `results/<lang>/<case>/` 下；
- **判分以 harness 输出为准**，代理自写脚本的结果不计分。

## 4. 评分维度

每个案例：

| 维度 | 权重 | 说明 |
|---|---|---|
| 功能正确性 | 40% | cocotb 测试通过率（各测试点权重见 SPEC） |
| 面积 | 20% | Yosys 映射到 sky130_fd_sc_hd 的 `stat -liberty` 总面积 (µm²)，三语言归一化 |
| 时序 | 20% | OpenSTA `report_clock_min_period` 关键路径延迟 → 等效 Fmax，三语言归一化 |
| 功耗 | 20% | OpenSTA `report_power` 名义总功耗 (sky130 tt_025C_1v80, 100MHz, 默认翻转率)，三语言归一化，仅横向相对比较 |

综合报告由 `suite/common/harness/report.py` 生成。功能未全过的案例仍参与面积/时序/功耗比较，但会在报告中标注。

## 5. 环境

- 先 `source /fact_home/yiyangyuan/workspace/projects/hdl_compare/env.sh`（内部会 source `~/tools/env.sh`）；
- 可用工具：verilator 5.050、iverilog 13.0、cocotb 2.0.1、yosys 0.67、sv2v、scala-cli（Chisel 版本固定见模板）、swim + spadec（Spade v0.20.0）；
- 重负载（如 LibreLane 后端）必须 `sbatch -p eda`，登录节点只跑 harness 级别的轻任务。
