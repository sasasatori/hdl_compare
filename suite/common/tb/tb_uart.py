"""tb_uart: uart_trx 统一测试. 端口契约见 suite/cases/uart/SPEC.md.

位时间 = 16*div 个 clk; clk 周期 10ns. 测试用 div ∈ {2,3,4,7}.
所有 rxd 激励在 clk 下降沿附近切换, 保证对采样沿 0.5 周期建立时间.
"""
import random

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from tb_common import start_clock, do_reset, g, CLK_PERIOD_NS


def bit_ns(div):
    return 16 * div * CLK_PERIOD_NS


class RxDriver:
    """按理想波形驱动 dut.rxd."""

    def __init__(self, dut):
        self.dut = dut
        dut.rxd.value = 1

    async def send_byte(self, byte, div, stop_level=1, gap_clk=0):
        d = self.dut
        await FallingEdge(d.clk)
        await Timer(1, unit="ns")  # 避开沿
        d.rxd.value = 0  # start
        await Timer(bit_ns(div), unit="ns")
        for i in range(8):
            d.rxd.value = (byte >> i) & 1
            await Timer(bit_ns(div), unit="ns")
        d.rxd.value = stop_level
        await Timer(bit_ns(div), unit="ns")
        d.rxd.value = 1
        for _ in range(gap_clk):
            await RisingEdge(d.clk)

    async def glitch(self, div, ticks=4):
        """假起始: 低脉冲持续 ticks 个 tick (<8) 后回高."""
        d = self.dut
        await FallingEdge(d.clk)
        await Timer(1, unit="ns")
        d.rxd.value = 0
        await Timer(ticks * div * CLK_PERIOD_NS, unit="ns")
        d.rxd.value = 1


class RxCollector:
    def __init__(self, dut):
        self.dut = dut
        self.bytes = []  # (data, err)

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk)
            if g(d.rx_valid):
                self.bytes.append((g(d.rx_data), g(d.rx_err)))

    def clear(self):
        self.bytes.clear()


class TxMonitor:
    """解码 txd 波形: 触发于下降沿, 位中点采样."""

    def __init__(self, dut):
        self.dut = dut
        self.frames = []  # (byte, stop_ok, err_msg)

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await FallingEdge(d.txd)
            await Timer(bit_ns(self._div()) / 2, unit="ns")
            byte = 0
            errs = []
            if g(d.txd) != 0:
                errs.append("start位中点不为0")
            for i in range(8):
                await Timer(bit_ns(self._div()), unit="ns")
                byte |= g(d.txd) << i
            await Timer(bit_ns(self._div()), unit="ns")
            stop_ok = g(d.txd) == 1
            self.frames.append((byte, stop_ok, ";".join(errs)))

    def _div(self):
        return g(self.dut.div)


async def init(dut, div=4):
    dut.div.value = div
    dut.tx_data.value = 0
    dut.tx_valid.value = 0
    await start_clock(dut)
    await do_reset(dut)
    assert g(dut.txd) == 1, "复位期间 txd 必须为 1"
    assert g(dut.tx_ready) == 1, "复位期间 tx_ready 必须为 1"
    assert g(dut.tx_busy) == 0, "复位期间 tx_busy 必须为 0"


async def tx_push(dut, byte, timeout_ns=200000):
    """握手发送一个字节."""
    dut.tx_data.value = byte
    dut.tx_valid.value = 1
    await RisingEdge(dut.clk)
    n = 0
    while not g(dut.tx_ready):
        await RisingEdge(dut.clk)
        n += 1
        assert n * CLK_PERIOD_NS < timeout_ns, "tx_ready 超时"
    dut.tx_valid.value = 0


@cocotb.test()
async def test_tx_single(dut):
    await init(dut, div=4)
    mon = TxMonitor(dut)
    mon.start()
    await tx_push(dut, 0xA5)
    await Timer(bit_ns(4) * 11, unit="ns")
    assert len(mon.frames) == 1, f"应解码出1帧, 实际 {len(mon.frames)}"
    byte, stop_ok, errs = mon.frames[0]
    assert not errs, errs
    assert byte == 0xA5, f"解码 {byte:#x} != 0xA5"
    assert stop_ok, "停止位不为1"
    assert g(dut.tx_busy) == 0, "帧结束后 tx_busy 应为 0"
    assert g(dut.txd) == 1, "空闲 txd 应为 1"


@cocotb.test()
async def test_tx_backtoback(dut):
    rng = random.Random(7)
    await init(dut, div=2)
    mon = TxMonitor(dut)
    mon.start()
    data = [rng.randrange(256) for _ in range(16)]
    for b in data:
        await tx_push(dut, b)
    await Timer(bit_ns(2) * 12, unit="ns")
    got = [f[0] for f in mon.frames]
    assert all(f[1] for f in mon.frames), "存在停止位错误"
    assert got == data, f"连发解码不一致: {got} != {data}"


@cocotb.test()
async def test_rx_single(dut):
    await init(dut, div=4)
    drv = RxDriver(dut)
    col = RxCollector(dut)
    col.start()
    await drv.send_byte(0x3C, 4)
    await Timer(bit_ns(4) * 2, unit="ns")
    assert len(col.bytes) == 1, f"应收1字节, 实际 {len(col.bytes)}"
    data, err = col.bytes[0]
    assert data == 0x3C and err == 0, f"rx: data={data:#x} err={err}"


@cocotb.test()
async def test_rx_stream(dut):
    rng = random.Random(11)
    await init(dut, div=3)
    drv = RxDriver(dut)
    col = RxCollector(dut)
    col.start()
    data = [rng.randrange(256) for _ in range(48)]
    for b in data:
        await drv.send_byte(b, 3, gap_clk=rng.randint(0, 2))
    await Timer(bit_ns(3) * 2, unit="ns")
    got = [d for d, e in col.bytes]
    assert got == data, f"流接收不一致 (len {len(got)} vs {len(data)})"
    assert all(e == 0 for _, e in col.bytes), "不应有帧错误"


@cocotb.test()
async def test_rx_framing_err(dut):
    await init(dut, div=4)
    drv = RxDriver(dut)
    col = RxCollector(dut)
    col.start()
    await drv.send_byte(0x55, 4, stop_level=0)  # 停止位拉低
    await Timer(bit_ns(4), unit="ns")
    assert len(col.bytes) == 1, "帧错误也应给出 rx_valid 脉冲"
    data, err = col.bytes[0]
    assert err == 1, "停止位为0必须报 rx_err"
    # 恢复正常
    await drv.send_byte(0x77, 4)
    await Timer(bit_ns(4) * 2, unit="ns")
    assert len(col.bytes) == 2 and col.bytes[1] == (0x77, 0), "恢复后接收失败"


@cocotb.test()
async def test_rx_false_start(dut):
    await init(dut, div=4)
    drv = RxDriver(dut)
    col = RxCollector(dut)
    col.start()
    for ticks in (2, 4, 6):  # 均短于半位(8 tick)
        await drv.glitch(4, ticks)
        await Timer(bit_ns(4) * 2, unit="ns")
    assert len(col.bytes) == 0, f"假起始产生了 {len(col.bytes)} 个 rx_valid"


@cocotb.test()
async def test_loopback(dut):
    rng = random.Random(99)
    await init(dut, div=4)
    col = RxCollector(dut)
    col.start()

    async def loopback():
        while True:
            await RisingEdge(dut.clk)
            dut.rxd.value = g(dut.txd)

    cocotb.start_soon(loopback())
    data = [rng.randrange(256) for _ in range(32)]
    for i, b in enumerate(data):
        if i == 16:
            # 改 div 前必须等收发全空闲 (SPEC: div 只在空闲时改变)
            while g(dut.tx_busy) == 1:
                await RisingEdge(dut.clk)
            await Timer(bit_ns(4) * 2, unit="ns")  # 等 RX 收完末字节
            dut.div.value = 7
        await tx_push(dut, b)
    # 等 RX 收齐 (不依赖 tx_busy 时序, 避免帧间气泡误判)
    n = 0
    while len(col.bytes) < 32:
        await RisingEdge(dut.clk)
        n += 1
        assert n < 5000, "回环接收超时"
    got = [d for d, e in col.bytes]
    assert got == data, f"回环不一致: 收{len(got)} 发{len(data)}"
    assert all(e == 0 for _, e in col.bytes), "回环出现帧错误"


@cocotb.test()
async def test_reset_during_rx(dut):
    await init(dut, div=4)
    drv = RxDriver(dut)
    col = RxCollector(dut)
    col.start()
    # 发送中途异步复位
    cocotb.start_soon(drv.send_byte(0x12, 4))
    await Timer(bit_ns(4) * 3.3, unit="ns")
    await do_reset(dut, cycles=2)
    # 残余帧 + 可能的幻影帧全部流完 (残余 ≤10bit, 幻影译码 ≤10bit)
    await Timer(bit_ns(4) * 22, unit="ns")
    col.clear()
    # 复位后必须能正常接收
    await drv.send_byte(0xBE, 4)
    await Timer(bit_ns(4) * 2, unit="ns")
    assert col.bytes == [(0xBE, 0)], f"复位后接收失败: {col.bytes}"
