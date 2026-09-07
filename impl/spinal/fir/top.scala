//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// fir16: 16 抽头 Q1.15 定点 FIR, 位精确 round-half-up + 饱和
import spinal.core._

class fir16 extends Component {
  val clk = (in Bool()).setName("clk")
  val rst = (in Bool()).setName("rst")

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  val coef_we   = (in  Bool()).setName("coef_we")
  val coef_addr = (in  UInt(4 bits)).setName("coef_addr")
  val coef_data = (in  SInt(16 bits)).setName("coef_data")
  val in_valid  = (in  Bool()).setName("in_valid")
  val in_ready  = (out Bool()).setName("in_ready")
  val in_data   = (in  SInt(16 bits)).setName("in_data")
  val out_valid = (out Bool()).setName("out_valid")
  val out_ready = (in  Bool()).setName("out_ready")
  val out_data  = (out SInt(16 bits)).setName("out_data")

  val area = new ClockingArea(cd) {
    val hist  = Vec(Reg(SInt(16 bits)) init 0, 16)   // hist(0) 最新
    val coefs = Vec(Reg(SInt(16 bits)) init 0, 16)

    when(coef_we) {
      coefs(coef_addr) := coef_data
    }

    val outV = RegInit(False)
    val outD = Reg(SInt(16 bits)) init 0

    // 全流水全局冻结: 输出被反压时所有级保持 (零丢失); out_ready=1 时每拍 1 样本
    val stall  = outV && !out_ready
    in_ready := !stall
    val accept = in_valid && !stall

    when(accept) {
      for (k <- 15 to 1 by -1) hist(k) := hist(k - 1)
      hist(0) := in_data
    }

    // S1: 4 组部分积和 (每组 4 个 16x16 乘 + 36bit 累加), 与 python 参考位精确一致
    // tap0 直接用 in_data (与 hist 移位同沿捕获, 对齐 accept); 其余读 hist 寄存器
    // 注意: Spinal `+` 不扩位, 每个 32bit 积先 resize 到 36bit
    val grp = (0 to 3).map(j =>
      (0 to 3).map(k => {
        val t = 4 * j + k
        (coefs(t) * (if (t == 0) in_data else hist(t - 1))).resize(36)
      }).reduce(_ + _)
    )
    val s1V = RegInit(False)
    val s1D = Vec(Reg(SInt(36 bits)) init 0, 4)
    // S2: 总和
    val s2V = RegInit(False)
    val s2D = Reg(SInt(36 bits)) init 0
    // S3: round-half-up + 算术右移 + 饱和
    val s3V = RegInit(False)
    val s3D = Reg(SInt(21 bits)) init 0            // round/shift 后, 饱和前
    // S4: 饱和 (纯寄存器锥, 避免与加法树被 macc 合并)
    val s4V = RegInit(False)
    val s4D = Reg(SInt(16 bits)) init 0

    when(!stall) {
      s1V := accept
      for (j <- 0 to 3) s1D(j) := grp(j)
      s2V := s1V
      s2D := ((s1D(0) + s1D(1)).resize(36) + (s1D(2) + s1D(3)).resize(36)).resize(36)
      s3V := s2V
      s3D := (s2D + S(0x4000, 36 bits)) >> 15    // 算术右移
      s4V := s3V
      // 饱和检测用归约而非带符号比较: 高位段 [35:15] 非全同号即溢出
      val hi = s3D.asBits(20 downto 15)            // s3D = accR>>>15 的高 6 位
      val signBit = s3D.asBits(20)
      val ovf = !(hi.andR) && (hi.orR)             // 非全 1 且非全 0 -> 溢出
      when(ovf && !signBit)  { s4D := S(32767, 16 bits) }
        .elsewhen(ovf)       { s4D := S(-32768, 16 bits) }
        .otherwise           { s4D := s3D.asBits(15 downto 0).asSInt }
      outV := s4V
      outD := s4D
    }

    out_valid := outV
    out_data  := outD
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new fir16)
}
