//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

// firtool 把 SInt*SInt 降成"符号扩展后 32x32 无符号乘", yosys/abc 映射极慢
// (单个 157s) 且面积大. 改用 ExtModule 引用原生 Verilog 有符号乘, yosys 前端
// 能识别为 signed $mul (16x16), 映射快一个数量级. mult16s.sv 由 Main 写入 build/.
class mult16s extends ExtModule {
  val io = IO(new Bundle {
    val a = Input(SInt(16.W))
    val b = Input(SInt(16.W))
    val y = Output(SInt(32.W))
  })
}

class fir16 extends RawModule {
  val clk       = IO(Input(Clock()))
  val rst       = IO(Input(AsyncReset()))
  val coef_we   = IO(Input(Bool()))
  val coef_addr = IO(Input(UInt(4.W)))
  val coef_data = IO(Input(UInt(16.W)))
  val in_valid  = IO(Input(Bool()))
  val in_ready  = IO(Output(Bool()))
  val in_data   = IO(Input(UInt(16.W)))
  val out_valid = IO(Output(Bool()))
  val out_ready = IO(Input(Bool()))
  val out_data  = IO(Output(UInt(16.W)))

  def mul(a: SInt, b: SInt): SInt = {
    val m = Module(new mult16s)
    m.io.a := a
    m.io.b := b
    m.io.y
  }

  withClockAndReset(clk, rst) {
    // 系数 (Q1.15 有符号), 复位清零
    val h = RegInit(VecInit(Seq.fill(16)(0.S(16.W))))
    when(coef_we) {
      h(coef_addr) := coef_data.asSInt
    }

    // 输入历史: x(k) = x[n-k], x(0) 最新
    val x = RegInit(VecInit(Seq.fill(16)(0.S(16.W))))

    // 第一级流水线: 16 个乘积寄存器 (32 bit 有符号)
    val prod    = RegInit(VecInit(Seq.fill(16)(0.S(32.W))))
    val valid1  = RegInit(false.B)

    // 输出寄存器
    val outValidR = RegInit(false.B)
    val outDataR  = RegInit(0.S(16.W))

    val stall  = outValidR && !out_ready // 输出未被消费, 冻结全线
    val accept = in_valid && !stall

    in_ready  := !stall
    out_valid := outValidR
    out_data  := outDataR.asUInt
    // 16 个并行乘法器 (ExtModule, 原生有符号乘), 乘积对应 {in_data, x(0..14)}
    val prodNext = (0 until 16).map { k =>
      val sample = if (k == 0) in_data.asSInt else x(k - 1)
      mul(h(k), sample)
    }


    // 采样沿锁存乘积并移入新样本 (accept 已蕴含 !stall, 单层使能)
    when(accept) {
      for (k <- 0 until 16) {
        prod(k) := prodNext(k)
        x(k) := (if (k == 0) in_data.asSInt else x(k - 1))
      }
    }
    // 第二级: 平衡加法树 + 舍入 + 饱和 -> 输出寄存器
    val acc  = prod.reduceTree(_ +& _) // 36 bit 精确累加
    val accR = acc + 16384.S                  // round-half-up (+0x4000)
    val yRaw = accR >> 15                     // 算术右移
    val ySat = Mux(yRaw > 32767.S, 32767.S(16.W),
               Mux(yRaw < (-32768).S, (-32768).S(16.W), yRaw(15, 0).asSInt))
    when(!stall) {
      valid1    := accept
      outValidR := valid1
      outDataR  := ySat
    }
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new fir16,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
  // ExtModule 的 Verilog 定义, 与 fir16.sv 一起被 harness 收集 (build/*.sv)
  java.nio.file.Files.write(
    java.nio.file.Paths.get("build/mult16s.sv"),
    ("module mult16s(\n" +
      "  input  wire signed [15:0] io_a,\n" +
      "  input  wire signed [15:0] io_b,\n" +
      "  output wire signed [31:0] io_y\n" +
      ");\n" +
      "  assign io_y = io_a * io_b;\n" +
      "endmodule\n").getBytes
  )
}
