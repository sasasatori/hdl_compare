//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

// sync_fifo 参考实现 (套件自检): 深度16 位宽8 FWFT FIFO, 契约见 cases/fifo/SPEC.md
import chisel3._
import circt.stage.ChiselStage

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
    val mem    = Mem(16, UInt(8.W))
    val wr_ptr = RegInit(0.U(4.W))
    val rd_ptr = RegInit(0.U(4.W))
    val cnt    = RegInit(0.U(5.W))

    val full  = cnt === 16.U
    val empty = cnt === 0.U
    val pop   = out_valid && out_ready

    in_ready     := !full || pop   // SPEC: 满且同拍弹出时仍可写
    out_valid    := !empty
    out_data     := mem(rd_ptr)    // FWFT
    count        := cnt
    almost_full  := cnt >= 12.U
    almost_empty := cnt <= 4.U

    val push = in_valid && in_ready
    when(push) {
      mem(wr_ptr) := in_data
      wr_ptr := wr_ptr + 1.U
    }
    when(pop) {
      rd_ptr := rd_ptr + 1.U
    }
    when(push && !pop) {
      cnt := cnt + 1.U
    }.elsewhen(!push && pop) {
      cnt := cnt - 1.U
    }
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new sync_fifo,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
