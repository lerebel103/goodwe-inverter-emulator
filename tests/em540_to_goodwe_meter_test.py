from __future__ import annotations

from app.config import Em540BridgeConfig, GoodweEmulatorConfig
from app.datasources import em540_client as em540_module
from app.datasources.em540_client import Em540BridgeClient
from app.goodwe.register_map import build_register_map
from app.models import Snapshot


def _i32_to_lw_words(value: int) -> tuple[int, int]:
    raw = value if value >= 0 else (1 << 32) + value
    return raw & 0xFFFF, (raw >> 16) & 0xFFFF


def _u32_to_lw_words(value: int) -> tuple[int, int]:
    raw = value & 0xFFFFFFFF
    return raw & 0xFFFF, (raw >> 16) & 0xFFFF


def _make_bridge_registers() -> list[int]:
    base = 0x0102
    regs = [0] * 0x5F

    def set_u16(addr: int, val: int) -> None:
        regs[addr - base] = val & 0xFFFF

    def set_i16(addr: int, val: int) -> None:
        regs[addr - base] = val & 0xFFFF

    def set_i32_lw(addr: int, val: int) -> None:
        w0, w1 = _i32_to_lw_words(val)
        set_u16(addr, w0)
        set_u16(addr + 1, w1)

    def set_u32_lw(addr: int, val: int) -> None:
        w0, w1 = _u32_to_lw_words(val)
        set_u16(addr, w0)
        set_u16(addr + 1, w1)

    # System + phase powers use x10 scale in bridge map.
    set_i32_lw(0x0106, -12345)  # -1234.5W total
    set_i32_lw(0x0124, -4115)
    set_i32_lw(0x0132, -4115)
    set_i32_lw(0x0140, -4115)

    set_i32_lw(0x0128, 250)
    set_i32_lw(0x0136, 260)
    set_i32_lw(0x0144, 270)

    set_i32_lw(0x0126, 4200)
    set_i32_lw(0x0134, 4300)
    set_i32_lw(0x0142, 4400)

    set_i32_lw(0x0120, 2304)  # 230.4V
    set_i32_lw(0x012E, 2311)  # 231.1V
    set_i32_lw(0x013C, 2298)  # 229.8V

    set_i32_lw(0x0122, 5120)  # 5.120A
    set_i32_lw(0x0130, 4880)  # 4.880A
    set_i32_lw(0x013E, 5010)  # 5.010A

    set_i16(0x010D, 995)  # total PF
    set_i16(0x012B, 992)
    set_i16(0x0139, 991)
    set_i16(0x0147, 998)
    set_i16(0x0110, 501)  # 50.1Hz

    # Energies use x100 scale in bridge map.
    set_u32_lw(0x0112, 456789)  # 4567.89kWh import
    set_u32_lw(0x0116, 123456)  # 1234.56kWh export
    set_u32_lw(0x014C, 150000)
    set_u32_lw(0x014E, 151111)
    set_u32_lw(0x0150, 155678)

    return regs


class _OkResult:
    def __init__(self, registers: list[int]):
        self.registers = registers

    def isError(self) -> bool:
        return False


class _ErrResult:
    registers: list[int] = []

    def isError(self) -> bool:
        return True


class _FakeClient:
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[tuple[int, int, int]] = []
        self._registers = _make_bridge_registers()

    def connect(self) -> bool:
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        self.calls.append((address, count, device_id))
        if address == 0x0102:
            return _OkResult(self._registers)
        return _ErrResult()

    def close(self) -> None:
        return None


class _FakeClientRetry(_FakeClient):
    def read_holding_registers(self, address: int, count: int, device_id: int):
        self.calls.append((address, count, device_id))
        if address == 0x0102:
            return _ErrResult()
        if address == 0x0103:
            return _OkResult(self._registers)
        return _ErrResult()


def test_em540_client_decodes_bridge_meter_fields(monkeypatch):
    holder: dict[str, _FakeClient] = {}

    def factory(host: str, port: int, timeout: float, **kwargs):
        inst = _FakeClient(host, port, timeout)
        holder["client"] = inst
        return inst

    monkeypatch.setattr(em540_module, "ModbusTcpClient", factory)

    cfg = Em540BridgeConfig(host="127.0.0.1", port=5001, slave_id=1, timeout=1.0)
    data = Em540BridgeClient(cfg).read()

    assert data["meter_power_w"] == -1234
    assert data["meter_power_l1_w"] == -411
    assert data["meter_reactive_power_total_w"] == 78
    assert data["meter_apparent_power_total_w"] == 1290
    assert data["meter_voltage_l1_v"] == 230.4
    assert data["meter_current_l2_a"] == 4.88
    assert data["meter_frequency_hz"] == 50.1
    assert data["meter_e_total_imp_kwh"] == 4567.89
    assert holder["client"].calls[0][0] == 0x0102


def test_em540_client_retries_on_one_based_bridge_offset(monkeypatch):
    holder: dict[str, _FakeClientRetry] = {}

    def factory(host: str, port: int, timeout: float, **kwargs):
        inst = _FakeClientRetry(host, port, timeout)
        holder["client"] = inst
        return inst

    monkeypatch.setattr(em540_module, "ModbusTcpClient", factory)

    cfg = Em540BridgeConfig(host="127.0.0.1", port=5001, slave_id=1, timeout=1.0)
    data = Em540BridgeClient(cfg).read()

    assert data["meter_power_w"] == -1234
    assert [c[0] for c in holder["client"].calls[:2]] == [0x0102, 0x0103]


def test_em540_to_goodwe_meter_registers_end_to_end(monkeypatch):
    monkeypatch.setattr(
        em540_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeClient(host, port, timeout, **kwargs),
    )

    cfg = Em540BridgeConfig(host="127.0.0.1", port=5001, slave_id=1, timeout=1.0)
    update = Em540BridgeClient(cfg).read()

    snap = Snapshot()
    for key, value in update.items():
        setattr(snap, key, value)

    regs = build_register_map(snap, GoodweEmulatorConfig())

    # Signed total active power at 36025/36026 should represent -1234.
    assert regs[36025] == 0xFFFF
    assert regs[36026] == 0xFB2E

    # Frequency and PF should reflect decoded bridge values.
    assert regs[36014] == 5010
    assert regs[36013] == 995

    # Per-phase active power and extended import energy block should be populated.
    assert regs[36019] == 0xFFFF
    assert regs[36020] == 0xFE65
    assert (regs[36120] | regs[36121] | regs[36122] | regs[36123]) > 0
