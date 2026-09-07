"""tb_fir: fir16 统一测试. 位精确数学定义见 suite/cases/fir/SPEC.md."""
import random

import cocotb
from cocotb.triggers import RisingEdge

from tb_common import start_clock, do_reset, tick, g, gs, s16, ValidReadySource, ValidReadySink

NTAP = 16


def fir_model(coefs, hist):
    """coefs: 16 个有符号 int; hist: 最新在前. 返回位精确 Q1.15 输出."""
    acc = 0
    for k in range(NTAP):
        x = hist[k] if k < len(hist) else 0
        acc += coefs[k] * x
    y = (acc + 0x4000) >> 15  # 算术右移 (python 负数 >> 即算术)
    return max(-32768, min(32767, y))


async def write_coefs(dut, coefs):
    assert len(coefs) == NTAP
    for i, c in enumerate(coefs):
        dut.coef_we.value = 1
        dut.coef_addr.value = i
        dut.coef_data.value = s16(c)
        await RisingEdge(dut.clk)
    dut.coef_we.value = 0
    await RisingEdge(dut.clk)


class FirSession:
    """驱动输入流 + 校验输出流 (保序, 一进一出)."""

    def __init__(self, dut):
        self.dut = dut
        self.src = ValidReadySource(dut, "in", dut.clk)
        self.sink = ValidReadySink(dut, "out", dut.clk)
        self.coefs = [0] * NTAP
        self.hist = []
        self.expected = []
        self.errors = 0
        self.latency = None
        self._cycle = 0

    def start(self):
        cocotb.start_soon(self._monitor())

    async def _monitor(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk)
            self._cycle += 1
            if g(d.out_valid) and g(d.out_ready):
                assert self.expected, "out_valid 但无对应输入 (多出输出)"
                exp, in_cyc = self.expected.pop(0)
                got = gs(d.out_data, 16)
                if got != exp:
                    self.errors += 1
                    assert False, f"输出不符: got={got} expect={exp} (样本@{in_cyc})"
                if self.latency is None:
                    self.latency = self._cycle - in_cyc

    async def push(self, x, idle_after=0):
        self.hist.insert(0, x)
        self.expected.append((fir_model(self.coefs, self.hist), self._cycle))
        await self.src.send(lambda: setattr(self.dut.in_data, "value", s16(x)),
                            idle_after=idle_after)

    async def drain(self, timeout=2000):
        n = 0
        while self.expected:
            await RisingEdge(self.dut.clk)
            n += 1
            assert n < timeout, "drain 超时: 输出数少于输入数"


async def init(dut):
    d = dut
    d.coef_we.value = 0
    d.coef_addr.value = 0
    d.coef_data.value = 0
    await start_clock(d)
    await do_reset(d)
    assert g(d.out_valid) == 0, "复位后 out_valid 应为 0"
    assert g(d.in_ready) == 1, "复位后 in_ready 应为 1"
    s = FirSession(d)
    s.start()
    return s


@cocotb.test()
async def test_impulse(dut):
    rng = random.Random(1)
    s = await init(dut)
    await write_coefs(dut, [32767] + [0] * 15)  # y=x (量化到 ≤0.99997)
    s.coefs = [32767] + [0] * 15
    dut.out_ready.value = 1
    xs = [rng.randrange(-32768, 32768) for _ in range(32)]
    for x in xs:
        await s.push(x)
    await s.drain()
    assert s.latency is not None and s.latency <= 32, f"LAT={s.latency} 超界"
    dut._log.info(f"LAT={s.latency}")


@cocotb.test()
async def test_known_coefs(dut):
    s = await init(dut)
    coefs = [8192, 8192, -4096, 2048, 1024, -512, 256, -128,
             64, -32, 16, -8, 4, -2, 1, 16384]
    await write_coefs(dut, coefs)
    s.coefs = coefs
    dut.out_ready.value = 1
    for x in [0, 1000, -1000, 20000, -20000, 32767, -32768, 12345, -12345, 0,
              555, -555, 30000, -30000, 1, -1]:
        await s.push(x)
    await s.drain()


@cocotb.test()
async def test_random(dut):
    rng = random.Random(2024)
    s = await init(dut)
    coefs = [rng.randrange(-32768, 32768) for _ in range(NTAP)]
    await write_coefs(dut, coefs)
    s.coefs = coefs
    dut.out_ready.value = 1
    for i in range(200):
        x = rng.choice([rng.randrange(-32768, 32768), 32767, -32768, 0])
        await s.push(x, idle_after=rng.randint(0, 2))
    await s.drain()


@cocotb.test()
async def test_saturation(dut):
    s = await init(dut)
    dut.out_ready.value = 1
    # 正向饱和: 系数全 32767, 输入全 32767
    await write_coefs(dut, [32767] * NTAP)
    s.coefs = [32767] * NTAP
    for _ in range(NTAP + 2):
        await s.push(32767)
    # 负向饱和: 输入全 -32768
    for _ in range(NTAP + 2):
        await s.push(-32768)
    await s.drain()
    # 模型内部已校验; 再显式确认未回绕: 最后输出应为 -32768
    dut._log.info("saturation checked by model")


@cocotb.test()
async def test_backpressure(dut):
    rng = random.Random(555)
    s = await init(dut)
    coefs = [rng.randrange(-32768, 32768) for _ in range(NTAP)]
    await write_coefs(dut, coefs)
    s.coefs = coefs

    async def random_ready():
        while True:
            dut.out_ready.value = rng.randint(0, 1)
            await RisingEdge(dut.clk)

    cocotb.start_soon(random_ready())
    for _ in range(120):
        await s.push(rng.randrange(-32768, 32768), idle_after=rng.randint(0, 2))
    while s.expected:
        dut.out_ready.value = 1
        await RisingEdge(dut.clk)
    assert s.errors == 0


@cocotb.test()
async def test_throughput(dut):
    rng = random.Random(777)
    s = await init(dut)
    coefs = [rng.randrange(-32768, 32768) for _ in range(NTAP)]
    await write_coefs(dut, coefs)
    s.coefs = coefs
    dut.out_ready.value = 1
    c0 = None
    N = 512
    for i in range(N):
        if i == 0:
            pass
        await s.push(rng.randrange(-32768, 32768))  # 无气泡
        if c0 is None:
            c0 = s._cycle
    await s.drain()
    total = s._cycle - c0
    dut._log.info(f"N={N} total_cycles={total} LAT={s.latency}")
    assert total <= N + 32, f"吞吐违约: {total} > {N}+32"


@cocotb.test()
async def test_coef_reload(dut):
    rng = random.Random(31337)
    s = await init(dut)
    dut.out_ready.value = 1
    ca = [rng.randrange(-32768, 32768) for _ in range(NTAP)]
    await write_coefs(dut, ca)
    s.coefs = ca
    for _ in range(20):
        await s.push(rng.randrange(-32768, 32768))
    await s.drain()
    # 空闲换系数
    cb = [rng.randrange(-32768, 32768) for _ in range(NTAP)]
    await write_coefs(dut, cb)
    s.coefs = cb
    for _ in range(20):
        await s.push(rng.randrange(-32768, 32768))
    await s.drain()
