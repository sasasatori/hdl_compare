//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// uart_trx: 全双工 UART 8N1, 16x 过采样, div = clks per tick, 位时间 = 16*div
import spinal.core._

class uart_trx extends Component {
  val clk = (in Bool()).setName("clk")
  val rst = (in Bool()).setName("rst")

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  val div      = (in  UInt(16 bits)).setName("div")
  val tx_data  = (in  UInt(8 bits)).setName("tx_data")
  val tx_valid = (in  Bool()).setName("tx_valid")
  val tx_ready = (out Bool()).setName("tx_ready")
  val txd      = (out Bool()).setName("txd")
  val tx_busy  = (out Bool()).setName("tx_busy")
  val rxd      = (in  Bool()).setName("rxd")
  val rx_data  = (out UInt(8 bits)).setName("rx_data")
  val rx_valid = (out Bool()).setName("rx_valid")
  val rx_err   = (out Bool()).setName("rx_err")

  val area = new ClockingArea(cd) {
    // ---------------- TX ----------------
    val txIdle    = RegInit(True)               // 空闲
    val txShifter = Reg(UInt(10 bits)) init 0x3FF // {stop, data, start}
    val txBitCnt  = RegInit(U(0, 4 bits))       // 0..9
    val txTickCnt = RegInit(U(0, 4 bits))       // 0..15
    val txDivCnt  = RegInit(U(0, 16 bits))      // 0..div-1
    val txdR      = RegInit(True)
    txd := txdR

    val txAccept = txIdle && tx_valid
    when(txAccept) {
      txIdle    := False
      txShifter := (B"1'1" ## tx_data ## B"1'0").asUInt
      txBitCnt  := 0
      txTickCnt := 0
      txDivCnt  := 0
      txdR      := False                       // 起始位从接受沿开始
    } elsewhen(!txIdle) {
      when(txDivCnt === div - 1) {
        txDivCnt := 0
        when(txTickCnt === 15) {
          txTickCnt := 0
          when(txBitCnt === 9) {
            txIdle := True                    // 停止位结束
            txdR   := True
          } otherwise {
            txBitCnt := txBitCnt + 1
            txShifter := txShifter |>> 1
            txdR := txShifter(1)
          }
        } otherwise {
          txTickCnt := txTickCnt + 1
        }
      } otherwise {
        txDivCnt := txDivCnt + 1
      }
    }
    tx_ready := txIdle
    tx_busy  := !txIdle

    // ---------------- RX ----------------
    object RxState extends SpinalEnum {
      val IDLE, START, DATA, STOP = newElement()
    }
    val rxState   = RegInit(RxState.IDLE)
    val rxTickCnt = RegInit(U(0, 4 bits))
    val rxDivCnt  = RegInit(U(0, 16 bits))
    val rxBitCnt  = RegInit(U(0, 3 bits))
    val rxShift   = Reg(UInt(8 bits)) init 0
    val rxS1      = RegInit(False)
    val rxS2      = RegInit(False)
    val rxDataR   = Reg(UInt(8 bits)) init 0
    val rxValidR  = RegInit(False)
    val rxErrR    = RegInit(False)

    rx_data  := rxDataR
    rx_valid := rxValidR
    rx_err   := rxErrR
    rxValidR := False   // 默认: 单周期脉冲

    val rxTickEdge = rxDivCnt === div - 1   // 本拍末产生一个 tick

    def rxCountTicks(): Unit = {
      when(rxTickEdge) {
        rxDivCnt := 0
        rxTickCnt := rxTickCnt + 1
      } otherwise {
        rxDivCnt := rxDivCnt + 1
      }
    }

    switch(rxState) {
      is(RxState.IDLE) {
        rxTickCnt := 0
        rxDivCnt  := 0
        when(!rxd) {
          rxState   := RxState.START
          rxTickCnt := 0
          rxDivCnt  := 0
        }
      }
      is(RxState.START) {
        rxCountTicks()
        when(rxTickEdge && rxTickCnt === 7) {   // 半位点确认
          when(!rxd) {
            rxState   := RxState.DATA
            rxBitCnt  := 0
            rxTickCnt := 0                      // 重新计数: 确认点=起始位中点
            rxDivCnt  := 0                      // 数据位中点 = 确认点后 16 tick
          } otherwise {
            rxState := RxState.IDLE             // 假起始
          }
        }
      }
      is(RxState.DATA) {
        rxCountTicks()
        when(rxTickEdge && rxTickCnt === 13) { rxS1 := rxd }
        when(rxTickEdge && rxTickCnt === 14) { rxS2 := rxd }
        when(rxTickEdge && rxTickCnt === 15) {
          val maj = (rxS1 && rxS2) || (rxS1 && rxd) || (rxS2 && rxd)
          rxShift := (maj.asBits ## rxShift(7 downto 1).asBits).asUInt
          when(rxBitCnt === 7) {
            rxState := RxState.STOP
          } otherwise {
            rxBitCnt := rxBitCnt + 1
          }
        }
      }
      is(RxState.STOP) {
        rxCountTicks()
        when(rxTickEdge && rxTickCnt === 13) { rxS1 := rxd }
        when(rxTickEdge && rxTickCnt === 14) { rxS2 := rxd }
        when(rxTickEdge && rxTickCnt === 15) {
          val maj = (rxS1 && rxS2) || (rxS1 && rxd) || (rxS2 && rxd)
          rxDataR  := rxShift
          rxValidR := True
          rxErrR   := !maj
          rxState  := RxState.IDLE
        }
      }
    }
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new uart_trx)
}
