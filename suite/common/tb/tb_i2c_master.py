"""tb_i2c: i2c_master 统一测试. 端口/协议契约见 suite/cases/i2c_master/SPEC.md.

总线模型: 开漏 wired-AND. bus = mst_o & slv_o (0 任何人拉低, 1 全释放=上拉).
所有模型在 clk 上升沿采样 (数字监视器视角), div>=4 保证分辨率足够.
"""
import random

import cocotb
from cocotb.triggers import RisingEdge

from tb_common import start_clock, do_reset, g

ACK_ADDR = 0x50   # 从机 ACK 的地址
NACK_ADDR = 0x52  # 从机 NACK 的地址


class I2cSlave:
    """字节级 I2C 从机: 7bit 地址, 256 字节寄存器堆, 页写/当前地址读.
    stretch=True 时在每个 SCL 上升前随机延展 0..max_stretch clk."""

    def __init__(self, dut, clk, addr=ACK_ADDR, stretch=False, rng=None, max_stretch=10):
        self.dut = dut
        self.clk = clk
        self.addr = addr
        self.mem = [0] * 256
        self.ptr = 0
        self.sda_drv = 1  # 1=释放, 0=拉低
        self.scl_drv = 1
        self.stretch = stretch
        self.rng = rng or random.Random(0)
        self.max_stretch = max_stretch
        self.written = []  # (reg, data) 记录

    async def run(self):
        """事务循环; 重复 START 的沿已被检测消费, 直接进地址阶段."""
        wait_start = True
        while True:
            if wait_start:
                await self._wait_start()
            wait_start = True
            byte = await self._recv_byte()
            addr, rw = byte >> 1, byte & 1
            if addr != self.addr:
                # NACK: 不应答, 等 STOP 或重复 START (沿已消费则直接收新地址)
                ev = await self._wait_start_or_stop_bit()
                wait_start = (ev != "start")
                continue
            await self._send_bit(0)  # ACK
            if rw == 0:
                ev = await self._write_phase()
            else:
                ev = await self._read_phase()
            wait_start = (ev != "start")

    # ---- 物理层 ----
    async def _wait_start(self):
        """等 START: sda 下降且 scl 高."""
        prev_sda = 1
        while True:
            await RisingEdge(self.clk)
            sda, scl = g(self.dut.sda_i), g(self.dut.scl_i)
            if prev_sda == 1 and sda == 0 and scl == 1:
                return
            prev_sda = sda

    async def _wait_scl_rise(self):
        """等 scl_i 变高; stretch 模式下先拉低若干拍."""
        if self.stretch:
            n = self.rng.randint(0, self.max_stretch)
            if n:
                self.scl_drv = 0
                for _ in range(n):
                    await RisingEdge(self.clk)
                self.scl_drv = 1
        while True:
            await RisingEdge(self.clk)
            if g(self.dut.scl_i) == 1:
                return

    async def _wait_scl_fall(self):
        while True:
            await RisingEdge(self.clk)
            if g(self.dut.scl_i) == 0:
                return

    async def _recv_bit(self):
        await self._wait_scl_fall()   # 必须先在低区 (START 检测时 scl 仍高, 否则首bit提前采样)
        await self._wait_scl_rise()
        for _ in range(2):
            await RisingEdge(self.clk)
        b = g(self.dut.sda_i)  # 高电平中段采样
        await self._wait_scl_fall()
        return b

    async def _recv_byte(self):
        b = 0
        for _ in range(8):
            b = (b << 1) | await self._recv_bit()
        return b

    async def _send_bit(self, bit):
        """在 scl 低期间驱动 sda, 等一个完整 scl 脉冲, 结束后释放."""
        self.sda_drv = 0 if bit == 0 else 1
        await self._wait_scl_rise()
        await self._wait_scl_fall()
        self.sda_drv = 1  # 释放, 避免影响后续位

    # ---- 协议层 ----
    async def _write_phase(self):
        """收字节: 首字节为寄存器地址, 其后为数据. 返回 "stop"|"start"."""
        first = True
        while True:
            kind, b = await self._recv_byte_or_stop()
            if kind != "byte":
                return kind
            if first:
                self.ptr = b
                first = False
            else:
                self.mem[self.ptr] = b
                self.written.append((self.ptr, b))
                self.ptr = (self.ptr + 1) & 0xFF
            await self._send_bit(0)  # ACK

    async def _read_phase(self):
        """发字节直到主机 NACK. 返回 "stop"|"start"."""
        while True:
            data = self.mem[self.ptr]
            self.ptr = (self.ptr + 1) & 0xFF
            for i in range(8):
                await self._send_bit((data >> (7 - i)) & 1)
            self.sda_drv = 1
            ack = await self._recv_bit()  # 0=主机 ACK
            if ack == 1:
                return await self._wait_start_or_stop_bit()

    async def _recv_byte_or_stop(self):
        """收字节; 任意时刻出现 START/STOP (sda 变化且 scl 持续为高) 即返回事件."""
        b = 0
        prev_sda, prev_scl = g(self.dut.sda_i), g(self.dut.scl_i)

        async def step():
            """推进一拍, 返回 None 或事件字符串."""
            await RisingEdge(self.clk)
            sda, scl = g(self.dut.sda_i), g(self.dut.scl_i)
            ev = None
            if scl == 1 and prev_scl == 1 and sda != prev_sda:
                ev = "start" if sda == 0 else "stop"
            return sda, scl, ev

        for _ in range(8):
            # 等 scl 上升 (含事件检测)
            while True:
                sda, scl, ev = await step()
                if ev:
                    return (ev, None)
                prev_sda, prev_scl = sda, scl
                if scl == 1:
                    break
            # 高区中段采样 (再等2拍, 期间检测事件)
            for _ in range(2):
                sda, scl, ev = await step()
                if ev:
                    return (ev, None)
                prev_sda, prev_scl = sda, scl
            b = (b << 1) | g(self.dut.sda_i)
            # 等下降 (期间检测事件)
            while True:
                sda, scl, ev = await step()
                if ev:
                    return (ev, None)
                prev_sda, prev_scl = sda, scl
                if scl == 0:
                    break
        return ("byte", b)

    async def _wait_start_or_stop_bit(self):
        """等 sda 在 scl 高时的任意变化, 返回 "start"|"stop"."""
        prev_sda = g(self.dut.sda_i)
        while True:
            await RisingEdge(self.clk)
            sda, scl = g(self.dut.sda_i), g(self.dut.scl_i)
            if scl == 1 and sda != prev_sda:
                return "start" if sda == 0 else "stop"
            prev_sda = sda


class Bus:
    """wired-AND 总线解析 + 协议监视器."""

    def __init__(self, dut, clk):
        self.dut = dut
        self.clk = clk
        self.slaves = []
        self.errors = []
        self.starts = 0
        self.stops = 0

    def add_slave(self, slv):
        self.slaves.append(slv)

    def start(self):
        cocotb.start_soon(self._resolver())
        cocotb.start_soon(self._monitor())

    async def _resolver(self):
        d = self.dut
        while True:
            await RisingEdge(self.clk)
            scl_o, sda_o = g(d.scl_o), g(d.sda_o)
            scl = scl_o
            sda = sda_o
            for s in self.slaves:
                scl &= s.scl_drv
                sda &= s.sda_drv
            d.scl_i.value = scl
            d.sda_i.value = sda

    async def _monitor(self):
        d = self.dut
        prev_sda, prev_scl = 1, 1
        while True:
            await RisingEdge(self.clk)
            sda, scl = g(d.sda_i), g(d.scl_i)
            if scl == 1 and prev_scl == 1:
                if prev_sda == 1 and sda == 0:
                    self.starts += 1
                elif prev_sda == 0 and sda == 1:
                    self.stops += 1
            # SDA 变化时 SCL 必须已经变低 (同拍变 scl 允许, 下一拍 scl 必须已低)
            if sda != prev_sda and scl == 1 and prev_scl == 1:
                pass  # start/stop 已覆盖
            elif sda != prev_sda and scl == 1 and prev_scl == 0:
                # scl 刚变高同拍 sda 变化 -> 违规 (SDA 未在 SCL 低期间稳定)
                self.errors.append(f"SDA 在 SCL 上升同拍变化 @monitor")
            prev_sda, prev_scl = sda, scl


class MasterIf:
    """cmd/rsp 接口驱动."""

    def __init__(self, dut, clk):
        self.dut = dut
        self.clk = clk
        self.rsps = []  # (data, nack)

    def start(self):
        cocotb.start_soon(self._rsp_collector())

    async def _rsp_collector(self):
        while True:
            await RisingEdge(self.clk)
            if g(self.dut.rsp_valid):
                self.rsps.append((g(self.dut.rsp_data), g(self.dut.rsp_nack)))

    async def cmd(self, op, data=0, timeout=20000):
        d = self.dut
        d.cmd_op.value = op
        d.cmd_data.value = data
        d.cmd_valid.value = 1
        await RisingEdge(self.clk)
        n = 0
        while not g(d.cmd_ready):
            await RisingEdge(self.clk)
            n += 1
            assert n < timeout, "cmd_ready 超时"
        d.cmd_valid.value = 0

    async def wait_rsps(self, n, timeout=200000):
        c = 0
        while len(self.rsps) < n:
            await RisingEdge(self.clk)
            c += 1
            assert c < timeout, f"等待 rsp 超时: {len(self.rsps)}/{n}"


async def init(dut, div=8):
    dut.div.value = div
    dut.cmd_valid.value = 0
    dut.cmd_op.value = 0
    dut.cmd_data.value = 0
    dut.scl_i.value = 1
    dut.sda_i.value = 1
    await start_clock(dut)
    await do_reset(dut)
    assert g(dut.scl_o) == 1 and g(dut.sda_o) == 1, "复位后总线必须释放"
    assert g(dut.cmd_ready) == 1, "复位后 cmd_ready 应为 1"
    assert g(dut.busy) == 0, "复位后 busy 应为 0"
    m = MasterIf(dut, dut.clk)
    m.start()
    b = Bus(dut, dut.clk)
    return m, b


@cocotb.test()
async def test_start_stop(dut):
    m, b = await init(dut, div=8)
    b.start()
    await m.cmd(0)  # START
    await m.cmd(3)  # STOP
    for _ in range(100):
        await RisingEdge(dut.clk)
    assert b.starts == 1 and b.stops == 1, f"START/STOP 计数错误 {b.starts}/{b.stops}"
    assert not b.errors, b.errors
    assert g(dut.scl_i) == 1 and g(dut.sda_i) == 1, "STOP 后总线应空闲(双高)"


@cocotb.test()
async def test_write_ack(dut):
    m, b = await init(dut, div=8)
    slv = I2cSlave(dut, dut.clk)
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    await m.cmd(0)             # START
    await m.cmd(1, ACK_ADDR << 1 | 0)  # WRITE addr|W
    await m.cmd(1, 0x10)       # reg addr
    await m.cmd(1, 0xAB)       # data
    await m.cmd(3)             # STOP
    await m.wait_rsps(3)
    for _ in range(200):
        await RisingEdge(dut.clk)
    assert all(nack == 0 for _, nack in m.rsps), f"应全部 ACK: {m.rsps}"
    assert slv.written == [(0x10, 0xAB)], f"从机收到 {slv.written}"
    assert not b.errors, b.errors


@cocotb.test()
async def test_write_nack(dut):
    m, b = await init(dut, div=8)
    slv = I2cSlave(dut, dut.clk)
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    await m.cmd(0)
    await m.cmd(1, NACK_ADDR << 1 | 0)  # 从机不 ACK
    await m.wait_rsps(1)
    await m.cmd(3)
    for _ in range(100):
        await RisingEdge(dut.clk)
    assert m.rsps[0][1] == 1, f"应报 NACK: {m.rsps}"


@cocotb.test()
async def test_read(dut):
    m, b = await init(dut, div=8)
    slv = I2cSlave(dut, dut.clk)
    slv.mem[0x00] = 0x3C  # 当前地址读: 从 ptr=0 开始
    slv.mem[0x01] = 0x5A
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    await m.cmd(0)
    await m.cmd(1, ACK_ADDR << 1 | 1)  # READ
    await m.cmd(2, 0)                  # 读并 ACK
    await m.cmd(2, 1)                  # 读并 NACK (结束)
    await m.cmd(3)
    await m.wait_rsps(3)
    for _ in range(200):
        await RisingEdge(dut.clk)
    assert m.rsps[1][0] == 0x3C, f"读1: {m.rsps[1]}"
    assert m.rsps[2][0] == 0x5A, f"读2: {m.rsps[2]}"
    assert not b.errors, b.errors


@cocotb.test()
async def test_clock_stretch(dut):
    rng = random.Random(6)
    m, b = await init(dut, div=4)
    slv = I2cSlave(dut, dut.clk, stretch=True, rng=rng, max_stretch=10)
    slv.mem[0x00] = 0x99
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    await m.cmd(0)
    await m.cmd(1, ACK_ADDR << 1 | 1)
    await m.cmd(2, 1)
    await m.cmd(3)
    await m.wait_rsps(2)
    for _ in range(200):
        await RisingEdge(dut.clk)
    assert m.rsps[1][0] == 0x99, f"延展下读数错误: {m.rsps}"
    assert not b.errors, b.errors


@cocotb.test()
async def test_reg_read_seq(dut):
    m, b = await init(dut, div=8)
    slv = I2cSlave(dut, dut.clk)
    slv.mem[0x30] = 0xDE
    slv.mem[0x31] = 0xAD
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    # 经典序列: START, 写addr+reg, 重复START, 读2字节, STOP
    await m.cmd(0)
    await m.cmd(1, ACK_ADDR << 1 | 0)
    await m.cmd(1, 0x30)
    await m.cmd(0)             # 重复 START
    await m.cmd(1, ACK_ADDR << 1 | 1)
    await m.cmd(2, 0)
    await m.cmd(2, 1)
    await m.cmd(3)
    await m.wait_rsps(5)
    for _ in range(200):
        await RisingEdge(dut.clk)
    assert m.rsps[-2][0] == 0xDE and m.rsps[-1][0] == 0xAD, f"寄存器读错误: {m.rsps}"
    assert slv.ptr == 0x32, f"从机指针错误: {slv.ptr:#x}"
    assert b.starts == 2, f"应有2次START(含重复): {b.starts}"
    assert not b.errors, b.errors


@cocotb.test()
async def test_multi_byte(dut):
    rng = random.Random(2049)
    m, b = await init(dut, div=4)
    slv = I2cSlave(dut, dut.clk)
    b.add_slave(slv)
    b.start()
    cocotb.start_soon(slv.run())
    data = [rng.randrange(256) for _ in range(8)]
    await m.cmd(0)
    await m.cmd(1, ACK_ADDR << 1 | 0)
    await m.cmd(1, 0x40)  # 起始寄存器
    for x in data:
        await m.cmd(1, x)
    await m.cmd(3)
    await m.wait_rsps(10)
    for _ in range(300):
        await RisingEdge(dut.clk)
    exp = [(0x40 + i, x) for i, x in enumerate(data)]
    assert slv.written == exp, f"页写不一致: {slv.written} != {exp}"
    assert all(nack == 0 for _, nack in m.rsps), "页写中出现 NACK"
    assert not b.errors, b.errors
