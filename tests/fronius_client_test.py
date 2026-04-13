from __future__ import annotations

import struct

import pytest

from app.config import FroniusConfig
from app.datasources import fronius_client as fronius_module
from app.datasources.fronius_client import FroniusClient


class _OkResult:
    def __init__(self, value: int):
        self.registers = [value & 0xFFFF]

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
        self._map: dict[int, int] = {
            40083: 500,  # W (value)
            40084: -1 & 0xFFFF,  # W SF
            40096: 250,  # DC current
            40099: -1 & 0xFFFF,  # SF
            40097: 6230,  # DC voltage
            40100: -1 & 0xFFFF,  # SF
            40098: 3100,  # DC power
            40101: -1 & 0xFFFF,  # SF
            # Optional per-channel raw values (0.1V / 0.1A / 1W)
            41001: 6100,
            41002: 18,
            41003: 1098,
            41011: 6110,
            41012: 17,
            41013: 1002,
        }

    def connect(self) -> bool:
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        if count > 1:
            regs = [self._map.get(address + i, 0) for i in range(count)]
            return _OkMultiResult(regs)
        if address in self._map:
            return _OkResult(self._map[address])
        return _ErrResult()

    def close(self) -> None:
        return None


class _FakeClientNoChannels(_FakeClient):
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        super().__init__(host, port, timeout, **kwargs)
        for addr in (41001, 41002, 41003, 41011, 41012, 41013):
            self._map.pop(addr, None)


class _FakeModel160Client:
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._map: dict[int, int] = {
            # SunSpec signature
            40000: 0x5375,
            40001: 0x6E53,
            # Common model header (ID=1, L=2)
            40002: 1,
            40003: 2,
            # Placeholder common model data
            40004: 0,
            40005: 0,
            # Model 160 header (L=8 fixed + 2*20 module blocks)
            40006: 160,
            40007: 48,
            # Model 160 fixed block
            40008: 0xFFFF,  # DCA_SF = -1
            40009: 0xFFFF,  # DCV_SF = -1
            40010: 0x0000,  # DCW_SF = 0
            40011: 0x0000,  # DCWH_SF = 0
            40012: 0x0000,  # Evt hi
            40013: 0x0000,  # Evt lo
            40014: 2,  # N (two MPPT module entries)
            40015: 1,  # TmsPer
            # Module 1 block (20 regs, starts at 40016)
            40016: 1,  # ID
            40025: 18,  # DCA -> 1.8 A
            40026: 6100,  # DCV -> 610.0 V
            40027: 1098,  # DCW -> 1098 W
            # Module 2 block (starts at 40036)
            40036: 2,  # ID
            40045: 17,  # DCA -> 1.7 A
            40046: 6110,  # DCV -> 611.0 V
            40047: 1002,  # DCW -> 1002 W
            # End marker after model 160
            40056: 0xFFFF,
            40057: 0x0000,
        }

    def connect(self) -> bool:
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        regs = []
        for i in range(count):
            regs.append(self._map.get(address + i, 0))
        return _OkMultiResult(regs)

    def close(self) -> None:
        return None


class _FakeModel160BadScaleClient(_FakeModel160Client):
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        super().__init__(host, port, timeout, **kwargs)
        # Invalid SunSpec sunssf sentinel for DCA_SF.
        self._map[40008] = 0x8000


class _FakeModel160FourModulesClient(_FakeModel160Client):
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        super().__init__(host, port, timeout, **kwargs)
        # Model 160 header (L=8 fixed + 4*20 module blocks)
        self._map[40007] = 88
        self._map[40014] = 4

        # Module 3 block (starts at 40056)
        self._map[40056] = 3
        self._map[40065] = 10
        self._map[40066] = 6200
        self._map[40067] = 700

        # Module 4 block (starts at 40076)
        self._map[40076] = 4
        self._map[40085] = 9
        self._map[40086] = 6300
        self._map[40087] = 600

        # End marker after model 160
        self._map[40096] = 0xFFFF
        self._map[40097] = 0x0000


class _OkMultiResult:
    def __init__(self, values: list[int]):
        self.registers = [v & 0xFFFF for v in values]

    def isError(self) -> bool:
        return False


class _FakeModel103Client:
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._map: dict[int, int] = {
            # SunSpec signature
            40000: 0x5375,
            40001: 0x6E53,
            # Inverter model 103 header (three phase)
            40002: 103,
            40003: 50,
            # Current (AphA/B/C) with A_SF=-1
            40005: 123,
            40006: 98,
            40007: 105,
            40008: (-1) & 0xFFFF,
            # Voltage (PhVphA/B/C) with V_SF=-1
            40009: 2401,
            40010: 2398,
            40011: 2403,
            40012: (-1) & 0xFFFF,
            # W / WphA/B/C with W_SF=0
            40013: 1234,
            40014: 400,
            40015: 420,
            40016: 414,
            40017: 0,
            # Frequency with Hz_SF=-2
            40018: 5000,
            40019: (-2) & 0xFFFF,
            # VA / VAphA/B/C with VA_SF=0
            40020: 1310,
            40021: 430,
            40022: 440,
            40023: 440,
            40024: 0,
            # VAr / VAr_SF -> -220 var
            40025: (-220) & 0xFFFF,
            40026: (-70) & 0xFFFF,
            40027: (-80) & 0xFFFF,
            40028: (-70) & 0xFFFF,
            40029: 0,
            # End marker
            40054: 0xFFFF,
            40055: 0,
        }

    def connect(self) -> bool:
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        regs = []
        for i in range(count):
            regs.append(self._map.get(address + i, 0))
        return _OkMultiResult(regs)

    def close(self) -> None:
        return None


class _FakeModel103NotImplementedClient(_FakeModel103Client):
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        super().__init__(host, port, timeout, **kwargs)
        # uint16 "not implemented" for A/V/Hz/VA paths
        self._map[40005] = 0xFFFF
        self._map[40006] = 0xFFFF
        self._map[40007] = 0xFFFF
        self._map[40009] = 0xFFFF
        self._map[40010] = 0xFFFF
        self._map[40011] = 0xFFFF
        self._map[40018] = 0xFFFF
        self._map[40020] = 0xFFFF
        self._map[40021] = 0xFFFF
        self._map[40022] = 0xFFFF
        self._map[40023] = 0xFFFF


def _f32_regs(value: float) -> tuple[int, int]:
    packed = struct.pack(">f", value)
    hi, lo = struct.unpack(">HH", packed)
    return hi, lo


class _FakeModel113Client:
    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._map: dict[int, int] = {
            # SunSpec signature
            40000: 0x5375,
            40001: 0x6E53,
            # Inverter model 113 header (three phase float)
            40002: 113,
            40003: 60,
        }

        # Model 113 data starts at 40004. Populate only fields we read.
        def set_f32(reg_index: int, value: float) -> None:
            hi, lo = _f32_regs(value)
            addr = 40004 + reg_index
            self._map[addr] = hi
            self._map[addr + 1] = lo

        set_f32(2, 12.3)  # AphA
        set_f32(4, 9.8)  # AphB
        set_f32(6, 10.5)  # AphC
        set_f32(14, 240.1)  # PhVphA
        set_f32(16, 239.8)  # PhVphB
        set_f32(18, 240.3)  # PhVphC
        set_f32(20, 1234.0)  # W
        set_f32(22, 50.0)  # Hz
        set_f32(24, 1310.0)  # VA
        set_f32(26, -220.0)  # VAr
        set_f32(28, 0.94)  # PF
        set_f32(38, 31.5)  # TmpCab
        set_f32(40, 45.5)  # TmpSnk
        set_f32(42, 40.0)  # TmpTrns

        # End marker
        self._map[40066] = 0xFFFF
        self._map[40067] = 0

    def connect(self) -> bool:
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        regs = []
        for i in range(count):
            regs.append(self._map.get(address + i, 0))
        return _OkMultiResult(regs)

    def close(self) -> None:
        return None


def test_fronius_client_returns_channel_data_from_optional_registers(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeClient(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(
        host="127.0.0.1",
        port=502,
        slave_id=1,
    )

    data = FroniusClient(cfg).read()

    assert data["pv_power_w"] == 50
    assert data["pv1_voltage_v"] == 610.0
    assert data["pv1_current_a"] == 1.8
    assert data["pv1_power_w"] == 1098
    assert data["pv2_voltage_v"] == 611.0
    assert data["pv2_current_a"] == pytest.approx(1.7)
    assert data["pv2_power_w"] == 1002


def test_fronius_client_falls_back_to_dc_split_without_channel_registers(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeClientNoChannels(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, slave_id=1)
    data = FroniusClient(cfg).read()

    # dc_power = 310.0W -> split into two channels by default
    assert data["pv1_power_w"] == 155
    assert data["pv2_power_w"] == 155
    assert data["pv1_voltage_v"] == 623.0
    assert data["pv2_voltage_v"] == 623.0


def test_fronius_client_reads_sunspec_model_160_extended_pv_arrays(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeModel160Client(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, slave_id=1, sunspec_model_160_enabled=True)
    data = FroniusClient(cfg).read()

    assert data["pv1_voltage_v"] == 610.0
    assert data["pv1_current_a"] == 1.8
    assert data["pv1_power_w"] == 1098
    assert data["pv2_voltage_v"] == 611.0
    assert data["pv2_current_a"] == pytest.approx(1.7)
    assert data["pv2_power_w"] == 1002
    assert data["pv_power_w"] == 2100


def test_sunspec_model_160_rejects_invalid_scale_factors():
    client = _FakeModel160BadScaleClient("127.0.0.1", 502, 2.0)
    model_data = fronius_module._read_sunspec_model_160(
        client,
        slave_id=1,
        string_count=2,
        model_index={160: (40008, 48)},
    )
    assert model_data == {}


def test_fronius_client_limits_sunspec_model_160_to_two_strings(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeModel160FourModulesClient(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(
        host="127.0.0.1",
        port=502,
        slave_id=1,
        sunspec_model_160_enabled=True,
        pv_string_count=2,
    )
    data = FroniusClient(cfg).read()

    assert data["pv1_power_w"] == 1098
    assert data["pv2_power_w"] == 1002
    assert data["pv3_power_w"] == 0
    assert data["pv4_power_w"] == 0
    assert data["pv_power_w"] == 2100


def test_fronius_client_reads_inverter_ac_power_from_sunspec_model_103(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeModel103Client(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, slave_id=1, sunspec_model_160_enabled=False)
    data = FroniusClient(cfg).read()

    assert data["inverter_active_power_w"] == 1234
    assert data["inverter_power_l1_w"] == 400
    assert data["inverter_power_l2_w"] == 420
    assert data["inverter_power_l3_w"] == 414
    assert data["inverter_apparent_power_va"] == 1310
    assert data["inverter_apparent_power_l1_va"] == 430
    assert data["inverter_apparent_power_l2_va"] == 440
    assert data["inverter_apparent_power_l3_va"] == 440
    assert data["inverter_reactive_power_var"] == -220
    assert data["inverter_reactive_power_l1_var"] == -70
    assert data["inverter_reactive_power_l2_var"] == -80
    assert data["inverter_reactive_power_l3_var"] == -70
    assert data["inverter_voltage_l1_v"] == pytest.approx(240.1)
    assert data["inverter_voltage_l2_v"] == pytest.approx(239.8)
    assert data["inverter_voltage_l3_v"] == pytest.approx(240.3)
    assert data["inverter_current_l1_a"] == pytest.approx(12.3)
    assert data["inverter_current_l2_a"] == pytest.approx(9.8)
    assert data["inverter_current_l3_a"] == pytest.approx(10.5)
    assert data["inverter_frequency_hz"] == pytest.approx(50.0)


def test_fronius_client_handles_not_implemented_sentinels_for_model_103_scalars(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeModel103NotImplementedClient(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, slave_id=1, sunspec_model_160_enabled=False)
    data = FroniusClient(cfg).read()

    assert data["inverter_current_l1_a"] == 0.0
    assert data["inverter_current_l2_a"] == 0.0
    assert data["inverter_current_l3_a"] == 0.0
    assert data["inverter_voltage_l1_v"] == 0.0
    assert data["inverter_voltage_l2_v"] == 0.0
    assert data["inverter_voltage_l3_v"] == 0.0
    assert data["inverter_frequency_hz"] == 0.0
    assert data["inverter_apparent_power_va"] == 0
    assert data["inverter_apparent_power_l1_va"] == 0
    assert data["inverter_apparent_power_l2_va"] == 0
    assert data["inverter_apparent_power_l3_va"] == 0


def test_fronius_client_reads_inverter_ac_power_from_sunspec_model_113(monkeypatch):
    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FakeModel113Client(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, slave_id=1, sunspec_model_160_enabled=False)
    data = FroniusClient(cfg).read()

    assert data["inverter_active_power_w"] == 1234
    assert data["inverter_power_l1_w"] == 465
    assert data["inverter_power_l2_w"] == 370
    assert data["inverter_power_l3_w"] == 399
    assert data["inverter_apparent_power_va"] == 1310
    assert data["inverter_apparent_power_l1_va"] == 494
    assert data["inverter_apparent_power_l2_va"] == 393
    assert data["inverter_apparent_power_l3_va"] == 423
    assert data["inverter_reactive_power_var"] == -220
    assert data["inverter_reactive_power_l1_var"] == -83
    assert data["inverter_reactive_power_l2_var"] == -66
    assert data["inverter_reactive_power_l3_var"] == -71
    assert data["inverter_power_factor"] == pytest.approx(0.94, rel=1e-6)
    assert data["inverter_temperature_air_c"] == pytest.approx(31.5, rel=1e-6)
    assert data["inverter_temperature_radiator_c"] == pytest.approx(45.5, rel=1e-6)
    assert data["inverter_temperature_module_c"] == pytest.approx(40.0, rel=1e-6)
    assert data["inverter_voltage_l1_v"] == pytest.approx(240.1, rel=1e-6)
    assert data["inverter_voltage_l2_v"] == pytest.approx(239.8, rel=1e-6)
    assert data["inverter_voltage_l3_v"] == pytest.approx(240.3, rel=1e-6)
    assert data["inverter_current_l1_a"] == pytest.approx(12.3, rel=1e-6)
    assert data["inverter_current_l2_a"] == pytest.approx(9.8, rel=1e-6)
    assert data["inverter_current_l3_a"] == pytest.approx(10.5, rel=1e-6)
    assert data["inverter_frequency_hz"] == pytest.approx(50.0, rel=1e-6)


def test_scale_helpers_reject_out_of_range_scale_factor():
    regs = [1234, 32767]
    assert fronius_module._read_scaled_from_model_i16(regs, 0, 1) == 0.0
    assert fronius_module._read_scaled_from_model_u16(regs, 0, 1) == 0.0


def test_model_temperature_f32_uses_fallback_offsets_when_primary_is_zero():
    regs = [0] * 44

    def set_f32(reg_index: int, value: float) -> None:
        hi, lo = _f32_regs(value)
        regs[reg_index] = hi
        regs[reg_index + 1] = lo

    # Primary model-113 offsets (38/40/42) decode to 0.0 on this device.
    set_f32(38, 0.0)
    set_f32(40, 0.0)
    set_f32(42, 0.0)
    # Alternate offsets used by some Fronius firmware variants.
    set_f32(30, 33.2)
    set_f32(32, 48.1)
    set_f32(34, 41.7)

    assert fronius_module._read_model_temperature_f32(regs, primary_index=38, fallback_index=30) == pytest.approx(
        33.2, rel=1e-6
    )
    assert fronius_module._read_model_temperature_f32(regs, primary_index=40, fallback_index=32) == pytest.approx(
        48.1, rel=1e-6
    )
    assert fronius_module._read_model_temperature_f32(regs, primary_index=42, fallback_index=34) == pytest.approx(
        41.7, rel=1e-6
    )


def test_model_temperatures_reads_alternate_triplet_layout():
    regs = [0] * 48

    def set_f32(reg_index: int, value: float) -> None:
        hi, lo = _f32_regs(value)
        regs[reg_index] = hi
        regs[reg_index + 1] = lo

    # Firmware variant where temperatures are at (32, 36, 34) for air/module/radiator.
    set_f32(32, 30.4)
    set_f32(36, 41.2)
    set_f32(34, 46.9)

    air, module, radiator = fronius_module._read_model_temperatures(regs)
    assert air == pytest.approx(30.4, rel=1e-6)
    assert module == pytest.approx(41.2, rel=1e-6)
    assert radiator == pytest.approx(46.9, rel=1e-6)


def test_model_temperatures_falls_back_to_scaled_layout_when_float_is_zero():
    regs = [0] * 48
    regs[31] = 315  # 31.5C
    regs[32] = 455  # 45.5C
    regs[33] = 400  # 40.0C
    regs[35] = 0xFFFF  # sunssf = -1

    air, module, radiator = fronius_module._read_model_temperatures(regs)
    assert air == pytest.approx(31.5, rel=1e-6)
    assert module == pytest.approx(40.0, rel=1e-6)
    assert radiator == pytest.approx(45.5, rel=1e-6)


def test_model_temperatures_normalizes_oddly_scaled_float_values_and_mirrors_single_sensor():
    regs = [0] * 48

    def set_f32(reg_index: int, value: float) -> None:
        hi, lo = _f32_regs(value)
        regs[reg_index] = hi
        regs[reg_index + 1] = lo

    # One valid temperature encoded at unexpected scale (x100).
    set_f32(36, 7355.48)

    air, module, radiator = fronius_module._read_model_temperatures(regs)
    assert air == pytest.approx(73.5548, rel=1e-6)
    assert module == pytest.approx(73.5548, rel=1e-6)
    assert radiator == pytest.approx(73.5548, rel=1e-6)


def test_model_temperatures_backfills_missing_module_from_available_sensors():
    regs = [0] * 48

    def set_f32(reg_index: int, value: float) -> None:
        hi, lo = _f32_regs(value)
        regs[reg_index] = hi
        regs[reg_index + 1] = lo

    # Primary triplet yields air/radiator but module is missing.
    set_f32(38, 30.0)  # air
    set_f32(40, 50.0)  # radiator
    set_f32(42, 0.0)  # module missing

    air, module, radiator = fronius_module._read_model_temperatures(regs)
    assert air == pytest.approx(30.0, rel=1e-6)
    assert module == pytest.approx(40.0, rel=1e-6)
    assert radiator == pytest.approx(50.0, rel=1e-6)
