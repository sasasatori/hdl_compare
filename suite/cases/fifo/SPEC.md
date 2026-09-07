# CASE: fifo — 同步 FIFO (FWFT)

- 顶层模块名：`sync_fifo`
- 难度：★☆☆☆
- 考察点：指针/存储管理、边界条件、ready/valid 协议

## 1. 功能要求

深度 16、位宽 8 的同步 FIFO，**FWFT（First-Word Fall-Through）**模式：
`out_valid` 拉高期间，`out_data` 必须**组合地**呈现队列最旧元素（无需先给 `out_ready`）。

固定参数（不作 Verilog parameter，直接硬编码即可）：`DEPTH=16, WIDTH=8`。

## 2. 端口

| 端口 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| `clk` | in | 1 | 时钟，posedge |
| `rst` | in | 1 | 同步高有效复位 |
| `in_valid` | in | 1 | 写请求 |
| `in_ready` | out | 1 | 可写（= 非满） |
| `in_data` | in | 8 | 写数据 |
| `out_valid` | out | 1 | 可读（= 非空） |
| `out_ready` | in | 1 | 读请求 |
| `out_data` | out | 8 | 读数据（FWFT） |
| `count` | out | 5 | 当前元素个数（0..16） |
| `almost_full` | out | 1 | `count >= 12` |
| `almost_empty` | out | 1 | `count <= 4` |

## 3. 时序与协议

- `in_valid && in_ready` 的时钟沿 → 数据入队；`out_valid && out_ready` 的时钟沿 → 队首出队。
- **同拍推弹**（同周期同时发生入队和出队）必须正确：空队列时同拍推弹 → 新元素入队（count=1）；满队列时同拍推弹 → 弹出队首并压入新尾（count 保持 16）。
- `in_ready` / `out_valid` 必须反映**当拍**状态（允许纯组合输出）；同拍推弹时不得丢数据、不得多收。
- `count`、`almost_full`、`almost_empty` 在每拍给出**当前周期生效后**的占用状态（即与时钟沿更新后的占用一致；允许组合或寄存输出，测试在时钟沿后采样）。
- 复位（rst=1 期间任意时刻起至少一个时钟沿）：队列清空，`count=0`，`out_valid=0`，`in_ready=1`，`almost_empty=1`，`almost_full=0`，`out_data` 任意（不检查）。

## 4. 性能要求

- 满速推/弹可持续每拍 1 元素（无气泡）；测试将验证连续 500 拍满速传输零丢失。

## 5. 测试点（权重均等）

| 测试 | 内容 |
|---|---|
| `test_reset_state` | 复位期间与复位后各输出初值 |
| `test_single_xfer` | 单元素推入/弹出，标志位翻转序列 |
| `test_fill_and_drain` | 写满→逐拍弹出，校验 count/AF/AE/满空标志全程 |
| `test_simul_push_pop` | 边界同拍推弹：空时、满时、中间态 |
| `test_random_stress` | 随机推弹 5000 拍，与 Python 队列模型逐拍比对 |
| `test_full_throughput` | 背靠背满速传输计数正确性 |
