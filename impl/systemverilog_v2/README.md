# systemverilog_v2 — SVP 原语优先风格规约

本赛道用实验证明：**把"好结构"封装成原语后，AI 手写 SV 可以同时拿到 SV 的开发效率与 Spade 级的 PPA**。
写代码前必须先读本文件；**能用原语的结构一律用原语**，禁止徒手重写原语已覆盖的结构。

原语库：`impl/systemverilog_v2/lib/svp.sv`（harness 自动加入编译，直接实例化即可）。

## 懒写法 → 原语 对照表（评估实测依据）

| 徒手懒写法（坏结构） | 应使用的原语 | 实测差距 |
|---|---|---|
| `rx_shift[idx] <= x` 动态索引写（每位使能 mux+解码器） | `svp_shift`（移位=零逻辑） | uart 面积 -22% |
| `for: acc = acc + x[i]`（16 级线性进位链） | `svp_add_tree`（log2(N) 级平衡树） | fir 关键路径 21.2→16.6ns |
| 徒手 `(acc+0x4000)>>>15` + 钳位（位宽易错） | `svp_rnd_sat` | 位精确语义固化 |
| 徒手波特率/半周期计数器（相位易错位） | `svp_tick_gen`（含 cnt 输出供中点采样） | uart/i2c 共用 |
| 徒手 FIFO 指针（满/空/同拍推弹边界） | `svp_fifo`（已验证结构） | 直接用 |

## 其他强制纪律（来自评估事故）

1. **宽度纪律**：声明即定型，乘法写清 `<W'1>x<W'2> → <W'1+W'2>`；符号数一律 `signed` 声明，禁止靠上下文推断符号。
2. **使能扇出**：寄存器阵列的写使能按"元素/行"解码（每条 ≤32 负载），禁止单条使能驱动 ≥64 个 DFF（matmul 实测 128 负载 → 10.5ns 单级坏路径）。面积敏感处优先考虑移位装载（行间移位）替代使能阵列。
3. **寄存器"问才给"**：不写默认使能/默认赋值样板；状态寄存器一律在时钟沿后语义下描述，复位值写全。
4. **乘法器**：直接用行为级 `signed * signed`（宽度收窄正确时 yosys/abc 映射正常；不要手拼 Booth）。
5. 原语没有覆盖的结构（如 FSM）才徒手写；FSM 状态用 localparam 命名。

## 案例实现清单

- `fifo/src/sync_fifo.sv` — 直接实例化 `svp_fifo`
- `uart/src/uart_trx.sv` — `svp_shift`(10bit 帧） + `svp_tick_gen` + 3 采样多数表决
- `fir/src/fir16.sv` — 16 乘积 + `svp_add_tree #(16,32)` + `svp_rnd_sat`
- `matmul/src/matmul4x4.sv` — 迭代 4 乘法器（面积最优架构）+ `svp_add_tree #(4,32)` + 行移位装载的 C 寄存器（修使能扇出）
- `i2c_master/src/i2c_master.sv` — `svp_tick_gen` 四相位 FSM
