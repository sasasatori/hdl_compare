//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

class uart_trx extends RawModule {
  val clk      = IO(Input(Clock()))
  val rst      = IO(Input(AsyncReset()))
  val div      = IO(Input(UInt(16.W)))
  val tx_data  = IO(Input(UInt(8.W)))
  val tx_valid = IO(Input(Bool()))
  val tx_ready = IO(Output(Bool()))
  val txd      = IO(Output(Bool()))
  val tx_busy  = IO(Output(Bool()))
  val rxd      = IO(Input(Bool()))
  val rx_data  = IO(Output(UInt(8.W)))
  val rx_valid = IO(Output(Bool()))
  val rx_err   = IO(Output(Bool()))

  withClockAndReset(clk, rst) {
    // ---------------- 发送器 ----------------
    val sTxIdle :: sTxSend :: Nil = Enum(2)
    val txState  = RegInit(sTxIdle)
    val txShift  = RegInit(0.U(9.W)) // {stop=1, d7..d0}, bit0 先发
    val txBitCnt = RegInit(0.U(4.W)) // 0=start,1..8=data,9=stop
    val txTick   = RegInit(0.U(4.W)) // 0..15
    val txDivCnt = RegInit(0.U(16.W))
    val txdReg   = RegInit(true.B)

    txd      := txdReg
    tx_busy  := txState === sTxSend
    tx_ready := txState === sTxIdle

    when(txState === sTxIdle) {
      txdReg := true.B
      when(tx_valid) {
        txState  := sTxSend
        txShift  := Cat(1.U(1.W), tx_data)
        txBitCnt := 0.U
        txTick   := 0.U
        txDivCnt := 0.U
        txdReg   := false.B // 起始位
      }
    }.otherwise {
      val tickDone = txDivCnt === (div - 1.U)
      when(tickDone) { txDivCnt := 0.U }.otherwise { txDivCnt := txDivCnt + 1.U }
      when(tickDone) {
        when(txTick === 15.U) {
          txTick := 0.U
          when(txBitCnt === 9.U) {
            txState := sTxIdle // 停止位结束
            txdReg  := true.B
          }.otherwise {
            txBitCnt := txBitCnt + 1.U
            txdReg   := txShift(0)
            txShift  := txShift >> 1
          }
        }.otherwise {
          txTick := txTick + 1.U
        }
      }
    }

    // ---------------- 接收器 ----------------
    val sRxIdle :: sRxStart :: sRxData :: sRxStop :: Nil = Enum(4)
    val rxState  = RegInit(sRxIdle)
    val rxShift  = RegInit(0.U(8.W))
    val rxBitCnt = RegInit(0.U(4.W))
    val rxTick   = RegInit(0.U(4.W)) // 0..15, 位起始为 0
    val rxDivCnt = RegInit(0.U(16.W))
    val rxVotes  = RegInit(0.U(2.W))
    val rxDataR  = RegInit(0.U(8.W))
    val rxValidR = RegInit(false.B)
    val rxErrR   = RegInit(false.B)

    rx_data  := rxDataR
    rx_valid := rxValidR
    rx_err   := rxErrR
    val rxSkip   = RegInit(false.B) // 进 DATA 后首个 tick8 完成是起始位中点, 须跳过
    rxValidR := false.B // 单周期脉冲 (出错位同拍)

    val rxTickDone = rxDivCnt === (div - 1.U)

    switch(rxState) {
      is(sRxIdle) {
        when(!rxd) { // 检测到起始位沿
          rxState  := sRxStart
          rxTick   := 0.U
          rxDivCnt := 0.U
        }
      }
      is(sRxStart) {
        when(rxTickDone) {
          rxDivCnt := 0.U
          when(rxTick === 7.U) { // 半位处确认
            when(!rxd) {
              rxState := sRxData
              rxTick  := 8.U // 继续计数, 位边界在 15->0 回绕
              rxBitCnt := 0.U
              rxVotes := 0.U
              rxSkip  := true.B
            }.otherwise {
              rxState := sRxIdle // 假起始
            }
          }.otherwise {
            rxTick := rxTick + 1.U
          }
        }.otherwise {
          rxDivCnt := rxDivCnt + 1.U
        }
      }
      is(sRxData) {
        when(rxTickDone) {
          rxDivCnt := 0.U
          // 在 tick 6,7,8 完成边界采样 (位起始后 7,8,9 个 tick)
          when(rxTick === 8.U && rxSkip) {
            rxSkip := false.B // 起始位中点的 tick8 完成, 不是数据位
          }.otherwise {
            // 在 tick 6,7,8 完成边界采样 (位起始后 7,8,9 个 tick)
            when(rxTick === 6.U || rxTick === 7.U || rxTick === 8.U) {
              rxVotes := rxVotes + rxd.asUInt
            }
            when(rxTick === 8.U) {
              val maj = (rxVotes + rxd.asUInt) >= 2.U
              rxShift  := Cat(maj, rxShift(7, 1)) // LSB 先收
              rxBitCnt := rxBitCnt + 1.U
              rxVotes  := 0.U
              when(rxBitCnt === 7.U) {
                rxState := sRxStop
              }
            }
          }
          when(rxTick === 15.U) { rxTick := 0.U }.otherwise { rxTick := rxTick + 1.U }
        }.otherwise {
          rxDivCnt := rxDivCnt + 1.U
        }
      }
      is(sRxStop) {
        when(rxTickDone) {
          rxDivCnt := 0.U
          when(rxTick === 6.U || rxTick === 7.U || rxTick === 8.U) {
            rxVotes := rxVotes + rxd.asUInt
          }
          when(rxTick === 8.U) {
            val maj = (rxVotes + rxd.asUInt) >= 2.U
            rxDataR  := rxShift
            rxErrR   := !maj // 停止位应为 1
            rxValidR := true.B
            rxState  := sRxIdle // 停止位中点后即可回空闲
            rxVotes  := 0.U
          }
          rxTick := rxTick + 1.U
        }.otherwise {
          rxDivCnt := rxDivCnt + 1.U
        }
      }
    }
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new uart_trx,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
