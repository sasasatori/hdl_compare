//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// sync_fifo: 16x8 FWFT synchronous FIFO
import spinal.core._

class sync_fifo extends Component {
  val clk = (in Bool()).setName("clk")
  val rst = (in Bool()).setName("rst")

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  val in_valid     = (in  Bool()).setName("in_valid")
  val in_ready     = (out Bool()).setName("in_ready")
  val in_data      = (in  UInt(8 bits)).setName("in_data")
  val out_valid    = (out Bool()).setName("out_valid")
  val out_ready    = (in  Bool()).setName("out_ready")
  val out_data     = (out UInt(8 bits)).setName("out_data")
  val count        = (out UInt(5 bits)).setName("count")
  val almost_full  = (out Bool()).setName("almost_full")
  val almost_empty = (out Bool()).setName("almost_empty")

  val area = new ClockingArea(cd) {
    val mem   = Mem(UInt(8 bits), 16)
    val wrPtr = RegInit(U(0, 4 bits))
    val rdPtr = RegInit(U(0, 4 bits))
    val cnt   = RegInit(U(0, 5 bits))

    val pop  = out_ready && (cnt =/= 0)
    val push = in_valid && ((cnt < 16) || pop)

    when(push) {
      mem.write(wrPtr, in_data)
      wrPtr := wrPtr + 1
    }
    when(pop) {
      rdPtr := rdPtr + 1
    }
    when(push =/= pop) {
      when(push) { cnt := cnt + 1 } otherwise { cnt := cnt - 1 }
    }

    in_ready     := (cnt < 16) || pop
    out_valid    := cnt =/= 0
    out_data     := mem.readAsync(rdPtr)
    count        := cnt
    almost_full  := cnt >= 12
    almost_empty := cnt <= 4
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new sync_fifo)
}
