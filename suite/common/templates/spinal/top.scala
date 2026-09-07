//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// SpinalHDL 工程模板. 固定以上三行版本指令 (依赖已缓存).
// 用法: 顶层 Component 类名 = SPEC 顶层模块名 (小写下划线); 生成: scala-cli run .  ->  build/<top>.v
//
// 要点 (均已按契约预填, 勿改):
// - 端口逐个 in/out 声明: val 名 = 端口名 (不要用 io Bundle, 会带 io_ 前缀违反端口契约)
// - 时钟域: clk/rst 显式端口 + ClockDomain(..., resetKind=ASYNC/SYNC, resetActiveLevel=HIGH)
//   寄存器逻辑必须包在 ClockingArea(cd) 里; RegInit/RegNext 即用该域复位
// - 输出文件: SpinalConfig(targetDirectory = "build").generateVerilog(new <top>)
import spinal.core._

class sync_fifo extends Component {
  val clk = in Bool()
  val rst = in Bool()

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  // 案例端口 (以 fifo 为例):
  val in_valid     = in  Bool()
  val in_ready     = out Bool()
  val in_data      = in  UInt(8 bits)
  val out_valid    = out Bool()
  val out_ready    = in  Bool()
  val out_data     = out UInt(8 bits)
  val count        = out UInt(5 bits)
  val almost_full  = out Bool()
  val almost_empty = out Bool()

  val area = new ClockingArea(cd) {
    // TODO: 在这里实现 RTL 逻辑 (RegInit / when / Mem / ...)
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new sync_fifo)
}
