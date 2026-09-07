"""cocotb 公共工具: 时钟/复位/ready-valid 驱动与采集. cocotb 2.0.1 API.

注意: cocotb 在每个测试结束时会回收该测试内 start_soon 的协程,
因此每个测试都应调用 start_clock; 跨测试共享的监控协程不保留.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10  # 100 MHz 仿真时钟


async def start_clock(dut, period_ns=CLK_PERIOD_NS):
    cocotb.start_soon(Clock(dut.clk, period_ns, unit="ns").start())


async def do_reset(dut, cycles=3, hold_ns=1):
    """异步高有效复位: 立即拉起, 保持 cycles 个时钟沿后, 在下降沿附近释放."""
    dut.rst.value = 1
    await Timer(hold_ns, unit="ns")  # 验证异步有效性 (不等时钟沿)
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)  # 在时钟低半周释放, 避免沿竞争
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def tick(dut, n=1):
    """N 个时钟沿 + 1ns 稳定时间, 用于采样沿后寄存器输出."""
    for _ in range(n):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


def g(sig):
    """读取信号为无符号 int."""
    return int(sig.value)


def gs(sig, width):
    """读取信号为有符号 int (二进制补码)."""
    v = int(sig.value)
    if v >= (1 << (width - 1)):
        v -= 1 << width
    return v


class ValidReadySource:
    """在 (prefix_valid/ready + 数据) 接口上驱动; ready 等待带超时."""

    def __init__(self, dut, prefix, clk):
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.clk = clk
        self.valid.value = 0

    async def send(self, drive_fn, idle_after=0, timeout_cycles=5000):
        """drive_fn() 设置数据端口; 阻塞直到该拍被接受."""
        drive_fn()
        self.valid.value = 1
        await RisingEdge(self.clk)
        n = 0
        while not g(self.ready):
            await RisingEdge(self.clk)
            n += 1
            assert n < timeout_cycles, "source 等待 ready 超时"
        self.valid.value = 0
        for _ in range(idle_after):
            await RisingEdge(self.clk)

    async def send_random_gaps(self, drive_fn, rng, max_gap=3):
        await self.send(drive_fn, idle_after=rng.randint(0, max_gap))


class ValidReadySink:
    """采集 (prefix_valid/ready + 数据) 接口; ready 由本类驱动, 收到即撤."""

    def __init__(self, dut, prefix, clk):
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.clk = clk
        self.ready.value = 0
        self.received = []

    async def recv(self, sample_fn, ready_mode="always", rng=None, timeout_cycles=2000):
        """等待一个有效拍并采样. sample_fn()->value. ready_mode: always|random."""
        n = 0
        while True:
            if ready_mode == "always":
                self.ready.value = 1
            elif ready_mode == "random":
                self.ready.value = rng.randint(0, 1)
            await RisingEdge(self.clk)
            n += 1
            assert n < timeout_cycles, "sink timeout"
            if g(self.valid) and g(self.ready):
                v = sample_fn()
                self.received.append(v)
                self.ready.value = 0  # 收到即撤, 防止下一拍误收
                return v


def s16(v):
    """int -> Q1.15 二进制补码无符号表示."""
    return v & 0xFFFF


def pack_bytes(vals):
    """[b0,b1,b2,b3] -> 32bit, b0 在 LSB."""
    r = 0
    for i, b in enumerate(vals):
        r |= (b & 0xFF) << (8 * i)
    return r


def unpack_bytes(v, n=4):
    return [(v >> (8 * i)) & 0xFF for i in range(n)]


def s8(v):
    v &= 0xFF
    return v - 256 if v >= 128 else v


def pack_i32(vals):
    r = 0
    for i, x in enumerate(vals):
        r |= (x & 0xFFFFFFFF) << (32 * i)
    return r


def unpack_i32(v, n=4):
    out = []
    for i in range(n):
        x = (v >> (32 * i)) & 0xFFFFFFFF
        out.append(x - (1 << 32) if x >= (1 << 31) else x)
    return out
