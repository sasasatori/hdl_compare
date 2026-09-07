"""tb_matmul: matmul4x4 统一测试. 打包格式/协议见 suite/cases/matmul/SPEC.md."""
import random

import cocotb
from cocotb.triggers import RisingEdge

from tb_common import (start_clock, do_reset, g, pack_bytes, unpack_i32,
                       ValidReadySource, ValidReadySink)

LATENCY_LIMIT = 32


def matmul_model(a, b):
    """a, b: 4x4 int8 -> 4x4 int32."""
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


class MatmulSession:
    def __init__(self, dut):
        self.dut = dut
        self.src = ValidReadySource(dut, "in", dut.clk)
        self.sink = ValidReadySink(dut, "out", dut.clk)
        self.results = []
        self._cycle = 0

    def start(self):
        cocotb.start_soon(self._monitor())

    async def _monitor(self):
        d = self.dut
        rows = []
        while True:
            await RisingEdge(d.clk)
            self._cycle += 1
            if g(d.out_valid) and g(d.out_ready):
                rows.append(unpack_i32(g(d.c_row)))
                if len(rows) == 4:
                    self.results.append(list(rows))
                    rows = []

    async def run_case(self, a, b, gap_fn=None, ready_mode="always", rng=None):
        """送 4 个输入拍, 收 4 行输出 (经 monitor), 返回结果矩阵."""
        n0 = len(self.results)
        for i in range(4):

            def drive(i=i):
                self.dut.a_row.value = pack_bytes([x & 0xFF for x in a[i]])
                self.dut.b_row.value = pack_bytes([x & 0xFF for x in b[i]])

            await self.src.send(drive)
            if gap_fn:
                for _ in range(gap_fn()):
                    await RisingEdge(self.dut.clk)
        c_in = self._cycle
        # out_ready 驱动
        async def drive_ready():
            while len(self.results) < n0 + 1:
                if ready_mode == "always":
                    self.dut.out_ready.value = 1
                else:
                    self.dut.out_ready.value = rng.randint(0, 1)
                await RisingEdge(self.dut.clk)
            self.dut.out_ready.value = 0

        rp = cocotb.start_soon(drive_ready())
        n = 0
        first_row_cycle = None
        while len(self.results) < n0 + 1:
            await RisingEdge(self.dut.clk)
            n += 1
            if first_row_cycle is None and g(self.dut.out_valid):
                first_row_cycle = self._cycle
            assert n < 2000, "等待输出超时"
        await rp
        if ready_mode == "always" and first_row_cycle is not None:
            lat = first_row_cycle - c_in
            assert lat <= LATENCY_LIMIT, f"末输入->首输出延迟 {lat} > {LATENCY_LIMIT}"
        return self.results[-1]


async def init(dut):
    await start_clock(dut)
    await do_reset(dut)
    assert g(dut.in_ready) == 1, "复位后 in_ready 应为 1"
    assert g(dut.out_valid) == 0, "复位后 out_valid 应为 0"
    s = MatmulSession(dut)
    s.start()
    return s



@cocotb.test()
async def test_identity(dut):
    s = await init(dut)
    eye = [[1 if i == j else 0 for j in range(4)] for i in range(4)]
    c = await s.run_case(eye, eye)
    assert c == eye, f"I×I 应为 I, 得到 {c}"


@cocotb.test()
async def test_known(dut):
    s = await init(dut)
    a = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]]
    b = [[1, 0, 0, 1], [0, 1, 1, 0], [2, -1, 0, 1], [1, 1, 1, 1]]
    c = await s.run_case(a, b)
    assert c == matmul_model(a, b), f"已知矩阵结果错误: {c}"


@cocotb.test()
async def test_random(dut):
    rng = random.Random(4242)
    s = await init(dut)
    for t in range(20):
        a = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
        b = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
        c = await s.run_case(a, b, gap_fn=lambda: rng.randint(0, 2))
        assert c == matmul_model(a, b), f"第{t}组随机矩阵错误"


@cocotb.test()
async def test_extremes(dut):
    s = await init(dut)
    cases = [
        ([[-128] * 4 for _ in range(4)], [[-128] * 4 for _ in range(4)]),
        ([[127] * 4 for _ in range(4)], [[127] * 4 for _ in range(4)]),
        ([[127, -128] * 2 for _ in range(4)], [[-128, 127] * 2 for _ in range(4)]),
    ]
    for a, b in cases:
        c = await s.run_case(a, b)
        assert c == matmul_model(a, b), f"极值矩阵错误: {c}"


@cocotb.test()
async def test_backpressure(dut):
    rng = random.Random(8)
    s = await init(dut)
    a = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
    b = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
    c = await s.run_case(a, b, ready_mode="random", rng=rng)
    assert c == matmul_model(a, b), "背压下结果错误"


@cocotb.test()
async def test_backtoback(dut):
    rng = random.Random(1234)
    s = await init(dut)
    mats = []
    for _ in range(8):
        a = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
        b = [[rng.randrange(-128, 128) for _ in range(4)] for _ in range(4)]
        mats.append((a, b))
    exp = [matmul_model(a, b) for a, b in mats]

    async def driver():
        for a, b in mats:
            for i in range(4):
                def drive(i=i, a=a, b=b):
                    dut.a_row.value = pack_bytes([x & 0xFF for x in a[i]])
                    dut.b_row.value = pack_bytes([x & 0xFF for x in b[i]])
                await s.src.send(drive)

    cocotb.start_soon(driver())
    dut.out_ready.value = 1
    n = 0
    while len(s.results) < 8:
        await RisingEdge(dut.clk)
        n += 1
        assert n < 4000, "背靠背超时"
    dut.out_ready.value = 0
    assert s.results == exp, "背靠背结果/顺序错误"
