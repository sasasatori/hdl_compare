//> using scala 2.13.16
//> using dep org.chipsalliance::chisel:7.15.0
//> using plugin org.chipsalliance:::chisel-plugin:7.15.0

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

class i2c_master extends RawModule {
  val clk       = IO(Input(Clock()))
  val rst       = IO(Input(AsyncReset()))
  val div       = IO(Input(UInt(16.W)))
  val cmd_valid = IO(Input(Bool()))
  val cmd_ready = IO(Output(Bool()))
  val cmd_op    = IO(Input(UInt(2.W)))
  val cmd_data  = IO(Input(UInt(8.W)))
  val rsp_valid = IO(Output(Bool()))
  val rsp_data  = IO(Output(UInt(8.W)))
  val rsp_nack  = IO(Output(Bool()))
  val busy      = IO(Output(Bool()))
  val scl_o     = IO(Output(Bool()))
  val scl_i     = IO(Input(Bool()))
  val sda_o     = IO(Output(Bool()))
  val sda_i     = IO(Input(Bool()))

  withClockAndReset(clk, rst) {
    // 状态: 空闲 / START 序列 / STOP 序列 / 字节传输(写/读) / 完成脉冲
    val sIdle :: sStRelSda :: sStRelScl :: sStStart :: sStLow :: sStopSetup :: sStopHigh :: sStopRel :: sBitSetup :: sBitHigh :: sDone :: Nil = Enum(11)

    val state    = RegInit(sIdle)
    val cnt      = RegInit(0.U(16.W))   // 相位内 clk 计数
    val bitCnt   = RegInit(0.U(4.W))    // 0..7 数据位, 8 = ACK 位
    val shReg    = RegInit(0.U(8.W))    // 写: 待发字节; 读: 移位接收
    val isRead   = RegInit(false.B)
    val ackDrive = RegInit(false.B)     // READ 第 9 位驱动值 (0=ACK 拉低)
    val nackR    = RegInit(false.B)
    val rspDataR = RegInit(0.U(8.W))
    val rspVldR  = RegInit(false.B)
    val sclReg   = RegInit(true.B)
    val sdaReg   = RegInit(true.B)

    scl_o     := sclReg
    sda_o     := sdaReg
    cmd_ready := state === sIdle
    busy      := state =/= sIdle
    rsp_valid := rspVldR
    rsp_data  := rspDataR
    rsp_nack  := nackR

    rspVldR := false.B // 单周期脉冲

    val half  = (div >> 1) - 1.U // 高电平中点采样计数
    val phase = div - 1.U        // 半周期计数

    // 当前位应驱动的 SDA 值 (仅 SETUP 相位使用)
    val bitVal = Mux(bitCnt === 8.U,
                     Mux(isRead, ackDrive, true.B), // 读: 主驱 ACK/NACK; 写: 释放等 ACK
                     Mux(isRead, true.B, shReg(7))) // 读数据位: 主机释放 SDA

    switch(state) {
      is(sIdle) {
        cnt := 0.U
        when(cmd_valid) {
          switch(cmd_op) {
            is(0.U) { // START
              state := sStRelSda
              sdaReg := true.B
            }
            is(1.U) { // WRITE
              state := sBitSetup
              shReg := cmd_data
              isRead := false.B
              bitCnt := 0.U
            }
            is(2.U) { // READ
              state := sBitSetup
              isRead := true.B
              ackDrive := cmd_data(0)
              bitCnt := 0.U
              shReg := 0.U
            }
            is(3.U) { // STOP
              state := sStopSetup
            }
          }
        }
      }

      // ---- START: SDA 释放(SCL低) -> SCL 释放并等高 -> SDA 拉低(START) -> SCL 拉低 ----
      is(sStRelSda) {
        sclReg := false.B
        sdaReg := true.B
        when(cnt === phase) { cnt := 0.U; state := sStRelScl }
          .otherwise { cnt := cnt + 1.U }
      }
      is(sStRelScl) {
        sclReg := true.B
        sdaReg := true.B
        when(scl_i) {
          when(cnt === phase) { cnt := 0.U; state := sStStart }
            .otherwise { cnt := cnt + 1.U }
        }
      }
      is(sStStart) {
        sclReg := true.B
        sdaReg := false.B // START 条件
        when(cnt === phase) { cnt := 0.U; state := sStLow }
          .otherwise { cnt := cnt + 1.U }
      }
      is(sStLow) {
        sclReg := false.B
        when(cnt === phase) { cnt := 0.U; state := sIdle }
          .otherwise { cnt := cnt + 1.U }
      }

      // ---- STOP: SDA 拉低(SCL低) -> SCL 释放等高 -> SDA 释放(STOP) ----
      is(sStopSetup) {
        sclReg := false.B
        sdaReg := false.B
        when(cnt === phase) { cnt := 0.U; state := sStopHigh }
          .otherwise { cnt := cnt + 1.U }
      }
      is(sStopHigh) {
        sclReg := true.B
        sdaReg := false.B
        when(scl_i) {
          when(cnt === phase) { cnt := 0.U; state := sStopRel }
            .otherwise { cnt := cnt + 1.U }
        }
      }
      is(sStopRel) {
        sclReg := true.B
        sdaReg := true.B // SDA 上升沿 = STOP
        when(cnt === phase) { cnt := 0.U; state := sIdle }
          .otherwise { cnt := cnt + 1.U }
      }

      // ---- 字节位循环 (读写共用): SETUP(SCL低, 改SDA) -> HIGH(释放SCL, 等延展, 中点采样) ----
      is(sBitSetup) {
        sclReg := false.B
        when(cnt === 0.U) {
          sdaReg := bitVal // SCL 已低一整拍后才动 SDA
        }
        when(cnt === phase) {
          cnt := 0.U
          state := sBitHigh
        }.otherwise { cnt := cnt + 1.U }
      }
      is(sBitHigh) {
        sclReg := true.B
        when(scl_i) { // 时钟延展: scl_i 不高则一直等 (cnt 保持 0)
          // 中点采样
          when(cnt === half) {
            when(isRead && bitCnt < 8.U) {
              shReg := Cat(shReg(6, 0), sda_i) // MSB 先收
            }
            when(!isRead && bitCnt === 8.U) {
              nackR := sda_i // ACK 位: 0=ACK
            }
          }
          when(cnt === phase) {
            cnt := 0.U
            sclReg := false.B // 高电平结束, 拉低 SCL
            when(bitCnt === 8.U) {
              state := sDone
              when(isRead) { rspDataR := shReg }
            }.otherwise {
              bitCnt := bitCnt + 1.U
              state := sBitSetup
              when(!isRead && bitCnt < 8.U) { shReg := shReg << 1 }
            }
          }.otherwise { cnt := cnt + 1.U }
        }
      }
      is(sDone) {
        sclReg := false.B
        rspVldR := true.B
        state := sIdle
        cnt := 0.U
      }
    }
  }
}

object Main extends App {
  ChiselStage.emitSystemVerilogFile(
    new i2c_master,
    args = Array("--target-dir", "build"),
    firtoolOpts = Array("--disable-all-randomization")
  )
}
