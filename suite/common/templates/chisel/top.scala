//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

// Chisel 工程模板. 固定以上三行版本指令 (评估环境已按其缓存依赖).
// 用法: 在本目录新增/修改 *.scala; 顶层模块名必须与 SPEC 一致 (用小写下划线类名).
// 生成: scala-cli run .   ->  build/<top>.sv
//
// 要点:
// - 继承 RawModule (无隐式 clock/reset 端口), 自行声明具名 clk/rst 端口;
// - 寄存器逻辑包在 withClockAndReset(clk, rst) 里 (rst 为同步高有效 Bool);
// - 端口用独立 IO(...) 声明, 不要用 Bundle (Bundle 会加 io_ 前缀, 违反端口契约);
// - ChiselStage.emitSystemVerilogFile(..., args = Array("--target-dir", "build"),
//   firtoolOpts = Array("--disable-all-randomization")) 已配好输出位置.
import chisel3._
import circt.stage.ChiselStage

// 以 fifo 为例, 顶层类名 = SPEC 顶层模块名 (sync_fifo):
class sync_fifo extends RawModule {
  val clk          = IO(Input(Clock()))
  val rst          = IO(Input(AsyncReset()))
  val in_valid     = IO(Input(Bool()))
  val in_ready     = IO(Output(Bool()))
  val in_data      = IO(Input(UInt(8.W)))
  val out_valid    = IO(Output(Bool()))
  val out_ready    = IO(Input(Bool()))
  val out_data     = IO(Output(UInt(8.W)))
  val count        = IO(Output(UInt(5.W)))
  val almost_full  = IO(Output(Bool()))
  val almost_empty = IO(Output(Bool()))

  withClockAndReset(clk, rst) {
    // TODO: 在这里实现 RTL 逻辑 (RegInit/Mem/when/...)
  }
}

object Main extends App {
  // 把 sync_fifo 换成你的顶层类名 (输出文件名 = 类名.sv)
  ChiselStage.emitSystemVerilogFile(
    new sync_fifo,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
