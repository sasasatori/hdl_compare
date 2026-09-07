//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// matmul4x4: 4x4 int8 矩阵乘, int32 精确累加
import spinal.core._

class matmul4x4 extends Component {
  val clk = (in Bool()).setName("clk")
  val rst = (in Bool()).setName("rst")

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  val in_valid  = (in  Bool()).setName("in_valid")
  val in_ready  = (out Bool()).setName("in_ready")
  val a_row     = (in  Bits(32 bits)).setName("a_row")
  val b_row     = (in  Bits(32 bits)).setName("b_row")
  val out_valid = (out Bool()).setName("out_valid")
  val out_ready = (in  Bool()).setName("out_ready")
  val c_row     = (out Bits(128 bits)).setName("c_row")

  val area = new ClockingArea(cd) {
    val aMat = Vec(Vec(Reg(SInt(8 bits)) init 0, 4), 4)
    val bMat = Vec(Vec(Reg(SInt(8 bits)) init 0, 4), 4)

    object St extends SpinalEnum {
      val IN, OUT = newElement()
    }
    val state  = RegInit(St.IN)
    val inCnt  = RegInit(U(0, 2 bits))
    val outCnt = RegInit(U(0, 2 bits))

    in_ready  := state === St.IN
    out_valid := state === St.OUT

    val accept = in_valid && in_ready
    when(accept) {
      for (k <- 0 to 3) {
        aMat(inCnt)(k) := a_row(8 * k + 7 downto 8 * k).asSInt
        bMat(inCnt)(k) := b_row(8 * k + 7 downto 8 * k).asSInt
      }
      when(inCnt === 3) {
        inCnt := 0
        state := St.OUT
        outCnt := 0
      } otherwise {
        inCnt := inCnt + 1
      }
    }

    // 16 个点积 (组合): C[i][j] = sum_k A[i][k]*B[k][j]
    def dot(i: Int, j: Int): SInt =
      (0 to 3).map(k => (aMat(i)(k) * bMat(k)(j)).resize(20)).reduce(_ + _).resize(32)

    val cRows = Vec((0 to 3).map(i =>
      Cat((0 to 3).map(j => dot(i, j).asBits))   // Cat 首元素在最低位 -> c_row[32*j +: 32] = C[i][j]
    ))
    c_row := cRows(outCnt)

    when(out_valid && out_ready) {
      when(outCnt === 3) {
        outCnt := 0
        state := St.IN
      } otherwise {
        outCnt := outCnt + 1
      }
    }
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new matmul4x4)
}
