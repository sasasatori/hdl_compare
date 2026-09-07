//> using scala 2.13.16
//> using dep com.github.spinalhdl::spinalhdl-core:1.15.0
//> using dep com.github.spinalhdl::spinalhdl-lib:1.15.0

// i2c_master: 字节级 I2C 主控制器 (开漏 4 线建模, 时钟延展, SCL 半周期 = div clk)
import spinal.core._

class i2c_master extends Component {
  val clk = (in Bool()).setName("clk")
  val rst = (in Bool()).setName("rst")

  val cd = ClockDomain(
    clock = clk,
    reset = rst,
    config = ClockDomainConfig(resetKind = ASYNC, resetActiveLevel = HIGH)
  )

  val div       = (in  UInt(16 bits)).setName("div")
  val cmd_valid = (in  Bool()).setName("cmd_valid")
  val cmd_ready = (out Bool()).setName("cmd_ready")
  val cmd_op    = (in  UInt(2 bits)).setName("cmd_op")
  val cmd_data  = (in  Bits(8 bits)).setName("cmd_data")
  val rsp_valid = (out Bool()).setName("rsp_valid")
  val rsp_data  = (out UInt(8 bits)).setName("rsp_data")
  val rsp_nack  = (out Bool()).setName("rsp_nack")
  val busy      = (out Bool()).setName("busy")
  val scl_o     = (out Bool()).setName("scl_o")
  val scl_i     = (in  Bool()).setName("scl_i")
  val sda_o     = (out Bool()).setName("sda_o")
  val sda_i     = (in  Bool()).setName("sda_i")

  val area = new ClockingArea(cd) {
    object St extends SpinalEnum {
      // IDLE/READY 可接受命令; READY = 事务中 SCL 保持低的命令间隙
      val IDLE, READY, START1, START2, RPT1, RPT2,
          WLOW, WREL, WHIGH, STOP1, STOP2, STOP3, STOP4 = newElement()
    }
    val state   = RegInit(St.IDLE)
    val cnt     = RegInit(U(0, 16 bits))
    val bitCnt  = RegInit(U(0, 4 bits))     // 当前位 0..8 (8 = ACK 位)
    val wdata   = Reg(Bits(8 bits)) init 0
    val ackBit  = RegInit(False)            // READ: 0=ACK(拉低) 1=NACK
    val isRead  = RegInit(False)
    val nack    = RegInit(False)
    val rxShift = Reg(Bits(8 bits)) init 0
    val sclOR   = RegInit(True)
    val sdaOR   = RegInit(True)
    val rspV    = RegInit(False)
    val rspD    = Reg(Bits(8 bits)) init 0
    val rspN    = RegInit(False)

    scl_o     := sclOR
    sda_o     := sdaOR
    rsp_valid := rspV
    rsp_data  := rspD.asUInt
    rsp_nack  := rspN
    busy      := (state =/= St.IDLE) && (state =/= St.READY)
    cmd_ready := (state === St.IDLE) || (state === St.READY)

    rspV := False   // 默认, 单周期脉冲

    val half = div >> 1
    def tickLast(period: UInt): Bool = cnt === period - 1

    val doAccept = cmd_valid && cmd_ready

    when(doAccept) {
      switch(cmd_op) {
        is(0) { // START
          when(state === St.IDLE) {
            sdaOR := False; cnt := 0; state := St.START1
          } otherwise { // 重复 START: 先释放 SDA, 抬 SCL, 再拉 SDA
            sdaOR := True; cnt := 0; state := St.RPT1
          }
        }
        is(1) { // WRITE
          wdata := cmd_data(6 downto 0) ## B"1'0"   // 之后每位: sdaOR := wdata(7) 再左移
          bitCnt := 0
          isRead := False
          sclOR := False
          sdaOR := cmd_data(7)
          cnt := 0
          state := St.WLOW
        }
        is(2) { // READ
          ackBit := cmd_data(0)
          bitCnt := 0
          isRead := True
          sclOR := False
          sdaOR := True
          cnt := 0
          state := St.WLOW
        }
        is(3) { // STOP
          when(state === St.READY) {
            sdaOR := False; cnt := 0; state := St.STOP1
          }
        }
      }
    }

    switch(state) {
      is(St.START1) { // SDA 已拉低, SCL 仍高: 建立时间 div/2
        when(tickLast(half)) { cnt := 0; sclOR := False; state := St.START2 }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.START2) { // SCL 低半周期
        when(tickLast(div)) { cnt := 0; state := St.READY }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.RPT1) { // 重复 START: SDA 已释放, SCL 低, 等 div
        when(tickLast(div)) { cnt := 0; sclOR := True; state := St.RPT2 }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.RPT2) { // 等 SCL 实际变高 (含延展), 再高电平保持 div
        when(scl_i) {
          when(tickLast(div)) { cnt := 0; sdaOR := False; state := St.START1 }
            .otherwise { cnt := cnt + 1 }
        }
      }
      is(St.WLOW) { // SCL 低半周期, SDA 已为目标位
        when(tickLast(div)) { cnt := 0; sclOR := True; state := St.WREL }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.WREL) { // 等待 SCL 实际升高 (时钟延展)
        when(scl_i) { cnt := 0; state := St.WHIGH }
      }
      is(St.WHIGH) { // SCL 高半周期 div clk
        when(cnt === half) { // 高半周期中点采样
          when(isRead) {
            when(bitCnt < 8) { rxShift := rxShift(6 downto 0) ## sda_i }
          } otherwise {
            when(bitCnt === 8) { nack := sda_i }
          }
        }
        when(tickLast(div)) {
          sclOR := False
          when(bitCnt === 8) { // 字节完成
            state := St.READY
            rspV := True
            rspD := rxShift
            rspN := nack
          } otherwise {
            bitCnt := bitCnt + 1
            cnt := 0
            state := St.WLOW
            when(!isRead) {
              when(bitCnt === 7) { sdaOR := True }              // 下一位是 ACK: 释放
                .otherwise { sdaOR := wdata(7); wdata := wdata(6 downto 0) ## B"1'0" }
            } otherwise {
              when(bitCnt === 7) { sdaOR := ackBit }            // 第 9 位驱动 ACK/NACK
            }
          }
        } otherwise { cnt := cnt + 1 }
      }
      is(St.STOP1) { // SDA 已拉低, SCL 低半周期
        when(tickLast(div)) { cnt := 0; sclOR := True; state := St.STOP2 }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.STOP2) { // 等 SCL 实际变高
        when(scl_i) { cnt := 0; state := St.STOP3 }
      }
      is(St.STOP3) { // 高电平保持 div
        when(tickLast(div)) { cnt := 0; sdaOR := True; state := St.STOP4 }
          .otherwise { cnt := cnt + 1 }
      }
      is(St.STOP4) { // 总线空闲 cooldown div
        when(tickLast(div)) { cnt := 0; state := St.IDLE }
          .otherwise { cnt := cnt + 1 }
      }
      default { // IDLE / READY: 保持
      }
    }
  }
}

object Main extends App {
  SpinalConfig(targetDirectory = "build").generateVerilog(new i2c_master)
}
