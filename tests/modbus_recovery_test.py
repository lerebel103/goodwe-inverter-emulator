from __future__ import annotations

from app.config import Em540BridgeConfig, FroniusConfig, VictronConfig
from app.datasources import em540_client as em540_module
from app.datasources import fronius_client as fronius_module
from app.datasources import victron_client as victron_module
from app.datasources.em540_client import Em540BridgeClient
from app.datasources.fronius_client import FroniusClient
from app.datasources.victron_client import VictronClient


class _OkResult:
    def __init__(self, registers: list[int]):
        self.registers = registers

    def isError(self) -> bool:
        return False


class _ErrResult:
    registers: list[int] = []

    def isError(self) -> bool:
        return True


class _Em540RecoveryClient:
    connect_outcomes = [False, True]
    connect_calls = 0
    close_calls = 0

    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout

    def connect(self) -> bool:
        type(self).connect_calls += 1
        outcome = type(self).connect_outcomes[type(self).connect_calls - 1]
        return outcome

    def read_holding_registers(self, address: int, count: int, device_id: int):
        return _OkResult([0] * count)

    def close(self) -> None:
        type(self).close_calls += 1


class _FroniusRecoveryClient:
    created = 0
    close_calls = 0

    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        type(self).created += 1
        self._instance_number = type(self).created
        self._map = {
            40083: 500,
            40084: -1 & 0xFFFF,
            40096: 250,
            40099: -1 & 0xFFFF,
            40097: 6230,
            40100: -1 & 0xFFFF,
            40098: 3100,
            40101: -1 & 0xFFFF,
        }

    def connect(self) -> bool:
        self.connected = True
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        if self._instance_number == 1:
            raise OSError("transient socket failure")
        if count != 1:
            return _ErrResult()
        if address in self._map:
            return _OkResult([self._map[address] & 0xFFFF])
        return _ErrResult()

    def close(self) -> None:
        type(self).close_calls += 1


class _VictronRecoveryClient:
    created = 0
    close_calls = 0

    def __init__(self, host: str, port: int, timeout: float, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        type(self).created += 1
        self._instance_number = type(self).created

    def connect(self) -> bool:
        self.connected = True
        return True

    def read_holding_registers(self, address: int, count: int, device_id: int):
        if self._instance_number == 1:
            return _ErrResult()
        if address == 840 and count == 7:
            return _OkResult([524, 3, 150, 64, 1, 20, 300])
        return _ErrResult()

    def close(self) -> None:
        type(self).close_calls += 1


def test_em540_retries_connect_and_recovers(monkeypatch):
    _Em540RecoveryClient.connect_outcomes = [False, True]
    _Em540RecoveryClient.connect_calls = 0
    _Em540RecoveryClient.close_calls = 0

    monkeypatch.setattr(
        em540_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _Em540RecoveryClient(host, port, timeout, **kwargs),
    )

    cfg = Em540BridgeConfig(host="127.0.0.1", port=502, timeout=0.2)
    data = Em540BridgeClient(cfg).read()

    assert data != {}
    assert _Em540RecoveryClient.connect_calls == 2
    assert _Em540RecoveryClient.close_calls == 1


def test_fronius_reconnects_after_transient_exception(monkeypatch):
    _FroniusRecoveryClient.created = 0
    _FroniusRecoveryClient.close_calls = 0

    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FroniusRecoveryClient(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, timeout=0.2)
    data = FroniusClient(cfg).read()

    assert data["pv_power_w"] == 50
    assert _FroniusRecoveryClient.created == 2
    assert _FroniusRecoveryClient.close_calls == 1


def test_victron_retries_after_read_error_and_recovers(monkeypatch):
    _VictronRecoveryClient.created = 0
    _VictronRecoveryClient.close_calls = 0

    monkeypatch.setattr(
        victron_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _VictronRecoveryClient(host, port, timeout, **kwargs),
    )

    cfg = VictronConfig(host="127.0.0.1", port=502, slave_id=100, timeout=0.2)
    data = VictronClient(cfg).read()

    assert data["battery_voltage_v"] == 52.4
    assert data["battery_soc_pct"] == 64
    assert _VictronRecoveryClient.created == 2
    assert _VictronRecoveryClient.close_calls == 1


def test_fronius_reuses_persistent_connection_after_success(monkeypatch):
    _FroniusRecoveryClient.created = 0
    _FroniusRecoveryClient.close_calls = 0

    monkeypatch.setattr(
        fronius_module,
        "ModbusTcpClient",
        lambda host, port, timeout, **kwargs: _FroniusRecoveryClient(host, port, timeout, **kwargs),
    )

    cfg = FroniusConfig(host="127.0.0.1", port=502, timeout=0.2)
    client = FroniusClient(cfg)

    # First read reconnects after injected transient error and succeeds.
    data1 = client.read()
    # Second read should reuse the healthy persistent connection.
    data2 = client.read()

    assert data1["pv_power_w"] == 50
    assert data2["pv_power_w"] == 50
    assert _FroniusRecoveryClient.created == 2
