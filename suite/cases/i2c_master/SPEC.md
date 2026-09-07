# CASE: i2c_master — I2C 主控制器

- 顶层模块名：`i2c_master`
- 难度：★★★★
- 考察点：复杂 FSM、开漏总线建模、时钟延展、协议时序生成

## 1. 功能要求

I2C 主设备（字节级命令引擎），支持标准/快速模式时序（由 `div` 决定）、START/STOP/重复 START、写字节、读字节（ACK/NACK 控制）、ACK 检测、**时钟延展（clock stretching）**处理。不要求多主机仲裁。

SCL 时基：**SCL 半周期 = `div` 个 clk 周期**（`div ≥ 4`，测试用 4、8、20）。

总线采用 4 线开漏建模（无 inout）：

- `scl_o = 0` → 主机拉低 SCL；`scl_o = 1` → 释放（由外部上拉变 1）
- `sda_o = 0` → 主机拉低 SDA；`sda_o = 1` → 释放
- `scl_i` / `sda_i` 为总线实际电平（主机必须以其为准，不得假设等于自己驱动的值）

## 2. 端口

| 端口 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| `clk` | in | 1 | 时钟，posedge |
| `rst` | in | 1 | 同步高有效复位 |
| `div` | in | 16 | SCL 半周期（clk 周期数），≥4 |
| `cmd_valid` | in | 1 | 命令有效 |
| `cmd_ready` | out | 1 | 可接受命令 |
| `cmd_op` | in | 2 | 0=START, 1=WRITE, 2=READ, 3=STOP |
| `cmd_data` | in | 8 | WRITE: 待写字节；READ: bit0=回应（0=ACK, 1=NACK）；其余忽略 |
| `rsp_valid` | out | 1 | 单周期脉冲：WRITE/READ 完成 |
| `rsp_data` | out | 8 | READ 读到的字节；WRITE 时任意 |
| `rsp_nack` | out | 1 | WRITE: 1=收到 NACK；READ: 任意 |
| `busy` | out | 1 | 引擎非空闲 |
| `scl_o` | out | 1 | 见上 |
| `scl_i` | in | 1 | 见上 |
| `sda_o` | out | 1 | 见上 |
| `sda_i` | in | 1 | 见上 |

复位状态：`scl_o=1, sda_o=1`（均释放），`cmd_ready=1, rsp_valid=0, busy=0`。

## 3. 时序与协议

命令流示例（写寄存器后读）：`START, WRITE(addr|W), WRITE(reg), START(重复), WRITE(addr|R), READ(NACK), STOP`。

- **START**：在 SCL、SDA 均高时，拉低 SDA，保持 ≥ `div/2` clk 后拉低 SCL（建立时间）。STOP 后总线空闲 ≥ 1 个半周期才能再发 START。
- **WRITE**：8 个数据位（MSB 先传）+ 1 个 ACK 位。每bit流程：SCL 低期间改变 SDA → 释放 SCL → 等待 `scl_i==1`（**含时钟延展等待**）→ 保持高电平 `div` clk → 拉低 SCL。第 9 位释放 SDA，在 SCL 高期间采样 `sda_i`（0=ACK）。采样点：SCL 高半周期的中点。完成后 `rsp_valid` 脉冲 + `rsp_nack`。
- **READ**：8 位期间释放 SDA，每bit在 SCL 高半周期中点采样；第 9 位按 `cmd_data[0]` 驱动 SDA（0=拉低=ACK）。完成后 `rsp_valid` + `rsp_data`。
- **STOP**：SCL 低时拉低 SDA → 释放 SCL，等待 `scl_i==1` → 保持 ≥ `div` clk → 释放 SDA（SDA 上升沿即 STOP）。STOP 完成后 `busy=0`。STOP 无 `rsp_valid`。
- **时钟延展**：释放 SCL 后，若 `scl_i==0` 则一直等待（超时 ≥ 1000 clk 可认为从机故障，但测试不会触发；实现不限超时行为）。
- `cmd_ready`：空闲且能接受下一条命令时为 1；命令在 `cmd_valid && cmd_ready` 时钟沿被接受。**命令不允许丢失**。START/STOP 命令从接受到完成期间 `busy=1`。
- SDA 只在 `scl_i==0` 时改变（START/STOP 除外）——测试的协议监视器将逐边沿校验。

## 4. 性能要求

- 连续多命令事务（测试注入 20 条命令的序列）全部正确完成；
- 从机随机时钟延展（每 bit 0~10 clk）下传输正确。

## 5. 测试点（权重均等）

| 测试 | 内容 |
|---|---|
| `test_start_stop` | START/STOP 波形时序（监视器校验建立/保持） |
| `test_write_ack` | 写从机地址 0x50(W)，从机 ACK → rsp_nack=0，波形逐位校验 |
| `test_write_nack` | 写 0x52(W)，从机 NACK → rsp_nack=1 |
| `test_read` | 读 1 字节（从机发 0x3C），主机 ACK；再读 1 字节 NACK + STOP |
| `test_clock_stretch` | 从机在随机位延展 SCL，校验传输正确性 |
| `test_reg_read_seq` | 完整“写寄存器地址 + 重复 START + 读 2 字节”事务 |
| `test_multi_byte` | 连续写 8 字节（页写），从机逐字节比对 |
