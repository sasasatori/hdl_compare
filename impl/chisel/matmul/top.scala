//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

class matmul4x4 extends RawModule {
  val clk       = IO(Input(Clock()))
  val rst       = IO(Input(AsyncReset()))
  val in_valid  = IO(Input(Bool()))
  val in_ready  = IO(Output(Bool()))
  val a_row     = IO(Input(UInt(32.W)))
  val b_row     = IO(Input(UInt(32.W)))
  val out_valid = IO(Output(Bool()))
  val out_ready = IO(Input(Bool()))
  val c_row     = IO(Output(UInt(128.W)))

  withClockAndReset(clk, rst) {
    val sCollect :: sComp :: sOutBeat :: Nil = Enum(3)
    val state = RegInit(sCollect)

    // 行主序存储: aR(i)(k) = A[i][k], bR(m)(j) = B[m][j]
    val aR = RegInit(VecInit(Seq.fill(4)(VecInit(Seq.fill(4)(0.S(8.W))))))
    val bR = RegInit(VecInit(Seq.fill(4)(VecInit(Seq.fill(4)(0.S(8.W))))))
    val cRow = RegInit(VecInit(Seq.fill(4)(0.S(32.W)))) // 当前输出行

    val inCnt   = RegInit(0.U(3.W)) // 输入拍计数 0..3
    val rowIdx  = RegInit(0.U(3.W)) // 当前计算/输出行 0..3
    val elemCnt = RegInit(0.U(3.W)) // 行内元素 0..3

    in_ready  := state === sCollect
    out_valid := state === sOutBeat

    // c_row: c_row[32*j +: 32] = C[row][j]
    c_row := Cat((3 to 0 by -1).map(j => cRow(j).asUInt))

    switch(state) {
      is(sCollect) {
        when(in_valid) {
          for (k <- 0 until 4) {
            aR(inCnt)(k) := a_row(8 * k + 7, 8 * k).asSInt
            bR(inCnt)(k) := b_row(8 * k + 7, 8 * k).asSInt
          }
          when(inCnt === 3.U) {
            inCnt   := 0.U
            rowIdx  := 0.U
            elemCnt := 0.U
            state   := sComp
          }.otherwise {
            inCnt := inCnt + 1.U
          }
        }
      }
      is(sComp) {
        // 每拍 4 个乘法器算一个元素: C[i][j] = sum_k A[i][k]*B[k][j]
        val i = rowIdx
        val j = elemCnt
        val prods = (0 until 4).map(k => aR(i)(k) * bR(k)(j)) // SInt(16)
        cRow(j) := prods.reduce(_ +& _)
        when(elemCnt === 3.U) {
          elemCnt := 0.U
          state   := sOutBeat
        }.otherwise {
          elemCnt := elemCnt + 1.U
        }
      }
      is(sOutBeat) {
        when(out_ready) {
          when(rowIdx === 3.U) {
            rowIdx := 0.U
            state  := sCollect
          }.otherwise {
            rowIdx  := rowIdx + 1.U
            elemCnt := 0.U
            state   := sComp
          }
        }
      }
    }
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new matmul4x4,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
