"""tb_fifo: sync_fifo 统一测试. 端口契约见 suite/cases/fifo/SPEC.md."""
import random
from collections import deque

import cocotb
from cocotb.triggers import RisingEdge, Timer

from tb_common import (start_clock, do_reset, tick, g, ValidReadySource,
                       ValidReadySink)

DEPTH, WIDTH = 16, 8
AF_TH, AE_TH = 12, 4


def check_flags(dut, occ, ctx=""):
    assert g(dut.count) == occ, f"{ctx}: count={g(dut.count)} != {occ}"
    assert g(dut.almost_full) == (1 if occ >= AF_TH else 0), f"{ctx}: almost_full"
    assert g(dut.almost_empty) == (1 if occ <= AE_TH else 0), f"{ctx}: almost_empty"
    assert g(dut.out_valid) == (1 if occ > 0 else 0), f"{ctx}: out_valid"
    assert g(dut.in_ready) == (1 if occ < DEPTH else 0), f"{ctx}: in_ready"


@cocotb.test()
async def test_reset_state(dut):
    await start_clock(dut)
    dut.in_valid.value = 0
    dut.in_data.value = 0
    dut.out_ready.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")  # 同步复位: 一个时钟沿后状态已复位
    assert g(dut.out_valid) == 0, "复位期间(沿后) out_valid 必须为 0"
    assert g(dut.in_ready) == 1, "复位期间(沿后) in_ready 必须为 1"
    await do_reset(dut)
    await tick(dut)
    check_flags(dut, 0, "复位后")


@cocotb.test()
async def test_single_xfer(dut):
    await start_clock(dut)
    src = ValidReadySource(dut, "in", dut.clk)
    sink = ValidReadySink(dut, "out", dut.clk)
    await do_reset(dut)

    await src.send(lambda: setattr(dut.in_data, "value", 0x5A))
    await tick(dut)
    check_flags(dut, 1, "推入1后")
    assert g(dut.out_data) == 0x5A, "FWFT: out_data 应立即呈现队首"

    v = await sink.recv(lambda: g(dut.out_data))
    assert v == 0x5A, f"读出 {v:#x} != 0x5A"
    await tick(dut)
    check_flags(dut, 0, "弹出后")


@cocotb.test()
async def test_fill_and_drain(dut):
    await start_clock(dut)
    src = ValidReadySource(dut, "in", dut.clk)
    sink = ValidReadySink(dut, "out", dut.clk)
    await do_reset(dut)

    model = deque()
    for i in range(DEPTH):
        await src.send(lambda i=i: setattr(dut.in_data, "value", i))
        model.append(i)
        await tick(dut)
        check_flags(dut, i + 1, f"填充{i + 1}")
        assert g(dut.out_data) == model[0], "FWFT 队首错误"

    # 满时 in_ready=0: 再推一拍应被拒绝
    dut.in_data.value = 0xEE
    dut.in_valid.value = 1
    await tick(dut)
    assert g(dut.in_ready) == 0, "满时 in_ready 必须为 0"
    dut.in_valid.value = 0

    for i in range(DEPTH):
        exp = model.popleft()
        v = await sink.recv(lambda: g(dut.out_data))
        assert v == exp, f"弹出序错误: {v} != {exp}"
        await tick(dut)
        check_flags(dut, DEPTH - 1 - i, f"排空{i + 1}")


@cocotb.test()
async def test_simul_push_pop(dut):
    await start_clock(dut)
    src = ValidReadySource(dut, "in", dut.clk)
    sink = ValidReadySink(dut, "out", dut.clk)
    await do_reset(dut)

    model = deque()

    async def cycle(push, pop, data):
        """驱动一拍推/弹, 返回实际发生的 (pushed, popped, pop_data)."""
        dut.in_valid.value = 1 if push else 0
        if push:
            dut.in_data.value = data
        dut.out_ready.value = 1 if pop else 0
        await RisingEdge(dut.clk)  # 该沿采样握手
        pushed = push and g(dut.in_ready)
        popped = pop and g(dut.out_valid)
        pdata = g(dut.out_data) if popped else None
        dut.in_valid.value = 0
        dut.out_ready.value = 0
        return pushed, popped, pdata

    # 1) 空时同拍推弹 -> count=1
    p, q, d = await cycle(True, True, 0x11)
    assert p and not q, "空时同拍: 应推入, 弹出无效"
    model.append(0x11)
    await tick(dut)
    check_flags(dut, 1, "空同拍后")

    # 2) 中间态同拍推弹
    p, q, d = await cycle(True, True, 0x22)
    assert p and q and d == 0x11, f"中间态同拍错误 d={d}"
    model.popleft()
    model.append(0x22)
    await tick(dut)
    check_flags(dut, 1, "中间态同拍后")
    assert g(dut.out_data) == 0x22

    # 3) 填满
    dut.out_ready.value = 0
    for i in range(DEPTH - 1):
        await src.send(lambda i=i: setattr(dut.in_data, "value", 0x80 + i))
        model.append(0x80 + i)
    await tick(dut)
    check_flags(dut, DEPTH, "填满后")

    # 4) 满时同拍推弹: 弹出队首, 压入新尾, count 不变
    p, q, d = await cycle(True, True, 0xFF)
    assert p and q, "满时同拍: 推弹都应发生"
    assert d == model[0], f"满时同拍弹错 {d:#x}"
    model.popleft()
    model.append(0xFF)
    await tick(dut)
    check_flags(dut, DEPTH, "满同拍后")

    # 5) 排空校验完整性
    for i in range(DEPTH):
        exp = model.popleft()
        v = await sink.recv(lambda: g(dut.out_data))
        assert v == exp, f"最终排空 {v:#x} != {exp:#x}"


@cocotb.test()
async def test_random_stress(dut):
    await start_clock(dut)
    rng = random.Random(42)
    dut.in_valid.value = 0
    dut.out_ready.value = 0
    await do_reset(dut)

    model = deque()
    for i in range(5000):
        push = rng.random() < 0.5
        pop = rng.random() < 0.5
        data = rng.randrange(256)
        dut.in_valid.value = 1 if push else 0
        dut.in_data.value = data
        dut.out_ready.value = 1 if pop else 0
        await RisingEdge(dut.clk)
        if push and g(dut.in_ready):
            model.append(data)
        if pop and g(dut.out_valid):
            exp = model.popleft()
            assert g(dut.out_data) == exp, f"stress@{i}: {g(dut.out_data):#x} != {exp:#x}"
        dut.in_valid.value = 0
        dut.out_ready.value = 0
        if i % 100 == 0:
            await Timer(1, unit="ns")
            check_flags(dut, len(model), f"stress@{i}")
    # 排空
    while model:
        dut.out_ready.value = 1
        await RisingEdge(dut.clk)
        if g(dut.out_valid):
            exp = model.popleft()
            assert g(dut.out_data) == exp


@cocotb.test()
async def test_full_throughput(dut):
    await start_clock(dut)
    dut.in_valid.value = 0
    dut.out_ready.value = 0
    await do_reset(dut)

    pushed, popped = 0, 0
    next_exp = 0
    N = 500
    dut.out_ready.value = 1
    dut.in_valid.value = 1
    for i in range(N + DEPTH + 2):
        dut.in_data.value = pushed & 0xFF
        await RisingEdge(dut.clk)
        if pushed < N and g(dut.in_ready):
            pushed += 1
        if g(dut.out_valid) and g(dut.out_ready):
            assert g(dut.out_data) == (next_exp & 0xFF), "满速流传输出错"
            next_exp += 1
            popped += 1
        if pushed >= N:
            dut.in_valid.value = 0
    assert pushed == N, f"推入数 {pushed} != {N}"
    assert popped == N, f"弹出数 {popped} != {N}: 满速流有气泡或丢失"
