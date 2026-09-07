//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

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
    val mem   = Mem(16, UInt(8.W))
    val rdPtr = RegInit(0.U(5.W)) // bit4 = wrap
    val wrPtr = RegInit(0.U(5.W))

    val cnt    = wrPtr - rdPtr
    val empty  = rdPtr === wrPtr
    val full   = (rdPtr(4) =/= wrPtr(4)) && (rdPtr(3, 0) === wrPtr(3, 0))
    val doPop  = !empty && out_ready
    val doPush = in_valid && (!full || doPop) // 满时同拍推弹: 弹出让出位置

    in_ready  := !full || doPop
    out_valid := !empty
    out_data  := mem.read(rdPtr(3, 0))
    count     := cnt

    when(doPush) {
      mem.write(wrPtr(3, 0), in_data)
      wrPtr := wrPtr + 1.U
    }
    when(doPop) {
      rdPtr := rdPtr + 1.U
    }

    almost_full  := cnt >= 12.U
    almost_empty := cnt <= 4.U
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new sync_fifo,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
