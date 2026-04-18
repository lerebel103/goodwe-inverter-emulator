from __future__ import annotations

import pytest
from pymodbus.constants import ExcCodes

from app.config import AppConfig
from app.goodwe.server import GoodweModbusServer
from app.main import EmulatorRuntime


class _FakeServer:
    def __init__(self):
        self.updated_payloads: list[dict[int, int]] = []
        self.mark_data_received_calls = 0
        self.mark_upstream_failed_calls = 0

    def update_holding_registers(self, values: dict[int, int]) -> None:
        self.updated_payloads.append(dict(values))

    def mark_data_received(self) -> None:
        self.mark_data_received_calls += 1

    def mark_upstream_failed(self) -> None:
        self.mark_upstream_failed_calls += 1

    def serve_forever(self) -> None:
        raise AssertionError("not used in unit tests")


class _Reader:
    def __init__(self, payloads: list[dict[str, float | int]]):
        self._payloads = list(payloads)

    def read(self) -> dict[str, float | int]:
        if self._payloads:
            return self._payloads.pop(0)
        return {}


def _valid_em540() -> dict[str, float | int]:
    return {
        "meter_power_w": 900,
        "meter_power_l1_w": 300,
        "meter_power_l2_w": 300,
        "meter_power_l3_w": 300,
        "meter_reactive_power_l1_w": 40,
        "meter_reactive_power_l2_w": 45,
        "meter_reactive_power_l3_w": 50,
        "meter_reactive_power_total_w": 135,
        "meter_apparent_power_l1_w": 320,
        "meter_apparent_power_l2_w": 330,
        "meter_apparent_power_l3_w": 340,
        "meter_apparent_power_total_w": 990,
        "meter_power_factor_l1": 0.97,
        "meter_power_factor_l2": 0.96,
        "meter_power_factor_l3": 0.95,
        "meter_power_factor_total": 0.96,
        "meter_frequency_hz": 49.98,
        "meter_voltage_l1_v": 229.4,
        "meter_voltage_l2_v": 230.1,
        "meter_voltage_l3_v": 231.0,
        "meter_current_l1_a": 1.3,
        "meter_current_l2_a": 1.4,
        "meter_current_l3_a": 1.5,
        "meter_e_total_exp_kwh": 12.34,
        "meter_e_total_imp_kwh": 56.78,
        "meter_e_total_imp_l1_kwh": 18.0,
        "meter_e_total_imp_l2_kwh": 19.0,
        "meter_e_total_imp_l3_kwh": 19.78,
    }


def _valid_fronius() -> dict[str, float | int]:
    return {
        "pv_power_w": 3000,
        "pv1_voltage_v": 612.3,
        "pv1_current_a": 1.8,
        "pv1_power_w": 1102,
        "pv2_voltage_v": 612.1,
        "pv2_current_a": 1.7,
        "pv2_power_w": 1034,
        "pv3_voltage_v": 610.0,
        "pv3_current_a": 1.2,
        "pv3_power_w": 732,
        "pv4_voltage_v": 0.0,
        "pv4_current_a": 0.0,
        "pv4_power_w": 0,
    }


def _valid_victron() -> dict[str, float | int]:
    return {
        "battery_voltage_v": 52.4,
        "battery_soc_pct": 64,
        "battery_power_w": 0,
        "battery_state": 0,
    }


def _make_runtime() -> tuple[EmulatorRuntime, _FakeServer]:
    runtime = EmulatorRuntime(AppConfig())
    fake_server = _FakeServer()
    runtime._server = fake_server
    return runtime, fake_server


def test_runtime_holds_circuit_open_until_all_enabled_sources_valid():
    runtime, fake_server = _make_runtime()
    runtime._em540 = _Reader([_valid_em540()])
    runtime._fronius = _Reader([{}])
    runtime._victron = _Reader([_valid_victron()])

    assert runtime._refresh_once() is False
    assert fake_server.mark_upstream_failed_calls == 1
    assert fake_server.mark_data_received_calls == 0
    assert fake_server.updated_payloads == []


def test_runtime_publishes_only_after_full_valid_cycle():
    runtime, fake_server = _make_runtime()
    runtime._em540 = _Reader([_valid_em540()])
    runtime._fronius = _Reader([_valid_fronius()])
    runtime._victron = _Reader([_valid_victron()])

    assert runtime._refresh_once() is True
    assert fake_server.mark_upstream_failed_calls == 0
    assert fake_server.mark_data_received_calls == 1
    assert len(fake_server.updated_payloads) == 1
    regs = fake_server.updated_payloads[0]
    assert regs[36052] == 2294
    assert regs[37007] == 64


def test_runtime_opens_circuit_and_stops_publishing_after_later_failure():
    runtime, fake_server = _make_runtime()
    runtime._em540 = _Reader([_valid_em540(), _valid_em540()])
    runtime._fronius = _Reader([_valid_fronius(), {}])
    runtime._victron = _Reader([_valid_victron(), _valid_victron()])

    assert runtime._refresh_once() is True
    assert runtime._refresh_once() is False
    assert fake_server.mark_data_received_calls == 1
    assert fake_server.mark_upstream_failed_calls == 1
    assert len(fake_server.updated_payloads) == 1


def test_modbus_server_returns_device_busy_while_circuit_open():
    server = GoodweModbusServer("127.0.0.1", 60001, 60002, 247, data_timeout=5.0)
    result = server._store.getValues(3, 36052, count=3)
    assert result == ExcCodes.DEVICE_BUSY

    server.mark_data_received()
    server.update_holding_registers({36052: 2294, 36053: 2301, 36054: 2310})
    result = server._store.getValues(3, 36052, count=3)
    assert result == [2294, 2301, 2310]


def test_modbus_server_keeps_circuit_closed_when_data_age_is_under_five_seconds(monkeypatch):
    server = GoodweModbusServer("127.0.0.1", 60001, 60002, 247, data_timeout=5.0)
    server.mark_data_received()
    server.update_holding_registers({36052: 2294})

    stale_start = 1000.0

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start)
    server.mark_data_received()

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start + 4.99)
    result = server._store.getValues(3, 36052, count=1)
    assert result == [2294]


def test_modbus_server_opens_circuit_after_data_age_exceeds_five_seconds(monkeypatch):
    server = GoodweModbusServer("127.0.0.1", 60001, 60002, 247, data_timeout=5.0)
    server.mark_data_received()
    server.update_holding_registers({36052: 2294})

    stale_start = 2000.0

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start)
    server.mark_data_received()

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start + 5.01)
    result = server._store.getValues(3, 36052, count=1)
    assert result == ExcCodes.DEVICE_BUSY


def test_upstream_failure_does_not_open_circuit_while_data_is_fresh(monkeypatch):
    server = GoodweModbusServer("127.0.0.1", 60001, 60002, 247, data_timeout=5.0)
    server.mark_data_received()
    server.update_holding_registers({36052: 2294})

    stale_start = 3000.0

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start)
    server.mark_data_received()

    monkeypatch.setattr("app.goodwe.server.time.monotonic", lambda: stale_start + 2.0)
    server.mark_upstream_failed()
    result = server._store.getValues(3, 36052, count=1)
    assert result == [2294]


def test_default_goodwe_data_timeout_is_five_seconds():
    cfg = AppConfig()
    assert cfg.goodwe_emulator.data_timeout == pytest.approx(5.0)


def test_runtime_applies_victron_battery_scaling_before_publishing():
    runtime, fake_server = _make_runtime()
    runtime._cfg.victron.battery_scale = 10.0
    runtime._cfg.victron.battery_voltage_min_v = 180.0
    runtime._cfg.victron.battery_voltage_max_v = 600.0

    runtime._em540 = _Reader([_valid_em540()])
    runtime._fronius = _Reader([_valid_fronius()])
    runtime._victron = _Reader(
        [
            {
                "battery_voltage_v": 52.4,
                "battery_soc_pct": 64,
                "battery_power_w": 4700,
                "battery_current_a": 90.0,
                "battery_max_charge_voltage_v": 57.6,
                "battery_min_discharge_voltage_v": 44.0,
                "battery_max_charge_current_a": 120.0,
                "battery_max_discharge_current_a": 150.0,
                "battery_capacity_ah": 200.0,
                "battery_consumed_ah": 50.0,
            }
        ]
    )

    assert runtime._refresh_once() is True
    regs = fake_server.updated_payloads[0]
    assert regs[35180] == 5240
    assert regs[35181] == 90
    assert regs[37007] == 64  # SOC %
    assert regs[37008] == 100  # SOH % (default)


def test_runtime_applies_synthetic_pv_and_grid_export_overrides():
    runtime, fake_server = _make_runtime()
    runtime._cfg.fronius.synthetic_pv_enabled = True
    runtime._cfg.fronius.synthetic_pv_total_power_w = 8200
    runtime._cfg.fronius.synthetic_pv1_voltage_v = 500.0
    runtime._cfg.fronius.synthetic_pv2_voltage_v = 500.0

    runtime._cfg.em540_bridge.synthetic_grid_export_enabled = True
    runtime._cfg.em540_bridge.synthetic_grid_total_power_w = -4500
    runtime._cfg.em540_bridge.synthetic_grid_frequency_hz = 50.0

    runtime._em540 = _Reader([_valid_em540()])
    runtime._fronius = _Reader([{}])
    runtime._victron = _Reader([_valid_victron()])

    assert runtime._refresh_once() is True

    regs = fake_server.updated_payloads[0]

    # PV total 8.2kW split evenly with 500V per string => 8.2A per string.
    assert regs[35103] == 5000
    assert regs[35104] == 82
    assert regs[35106] == 4100
    assert regs[35107] == 5000
    assert regs[35108] == 82
    assert regs[35110] == 4100
    assert regs[35138] == 8200

    # Grid export power is synthetic, but EM540 voltage still passes through from upstream.
    assert regs[36052] == 2294
    assert regs[36053] == 2301
    assert regs[36054] == 2310
    assert regs[36055] == 65  # abs(-1500 / 229.4) = 6.539 A → 65
    assert regs[36056] == 65  # abs(-1500 / 230.1) = 6.519 A → 65
    assert regs[36057] == 64  # abs(-1500 / 231.0) = 6.494 A → 64 (integer truncation)
    assert regs[36025] == 0xFFFF
    assert regs[36026] == 0xEE6C
