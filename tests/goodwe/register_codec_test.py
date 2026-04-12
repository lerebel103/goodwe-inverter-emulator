from app.goodwe.register_codec import put_ascii, put_f32, put_i32, put_u32, put_u64


def test_put_u32_and_i32():
    regs = {}
    put_u32(regs, 10, 0x12345678)
    assert regs[10] == 0x1234
    assert regs[11] == 0x5678

    put_i32(regs, 20, -2)
    assert regs[20] == 0xFFFF
    assert regs[21] == 0xFFFE


def test_put_ascii():
    regs = {}
    put_ascii(regs, 100, "ABCD", 2)
    assert regs[100] == 0x4142
    assert regs[101] == 0x4344


def test_put_u64_and_f32():
    regs = {}
    put_u64(regs, 200, 0x1122334455667788)
    assert regs[200] == 0x1122
    assert regs[201] == 0x3344
    assert regs[202] == 0x5566
    assert regs[203] == 0x7788

    put_f32(regs, 300, 12.5)
    assert regs[300] == 0x4148
    assert regs[301] == 0x0000
