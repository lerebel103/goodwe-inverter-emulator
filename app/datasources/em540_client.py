from __future__ import annotations

import logging

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

from app.config import Em540BridgeConfig
from app.datasources.modbus_resilience import ModbusClientCircuitBreaker, PersistentModbusSession

logger = logging.getLogger(__name__)


class Em540BridgeClient:
    def __init__(self, cfg: Em540BridgeConfig):
        self._cfg = cfg
        self._breaker = ModbusClientCircuitBreaker(
            "EM540",
            failure_threshold=2,
            cooldown_seconds=max(2.0, float(cfg.timeout) * 3.0),
        )
        self._session = PersistentModbusSession(
            source_name="EM540",
            create_client=self._build_client,
            breaker=self._breaker,
            retries=0,
        )

    def read(self) -> dict[str, float | int]:
        if not self._cfg.enabled:
            return {}

        return self._session.read(self._read_once)

    def _build_client(self) -> ModbusTcpClient:
        return ModbusTcpClient(
            self._cfg.host,
            port=self._cfg.port,
            timeout=self._cfg.timeout,
            retries=self._cfg.retry_count,
            framer=FramerType.SOCKET,
        )

    def _read_once(self, client: ModbusTcpClient) -> dict[str, float | int]:
        rr = client.read_holding_registers(address=0x0102, count=0x5F, device_id=self._cfg.slave_id)
        if rr.isError():
            # Some bridges expose one-based offsets. Retry with +1 address.
            rr = client.read_holding_registers(address=0x0103, count=0x5F, device_id=self._cfg.slave_id)
        if rr.isError():
            logger.warning("EM540 read error")
            return {}

        regs = rr.registers
        power_w = int(_i32lw(_reg(regs, 0x0106), _reg(regs, 0x0107)) / 10.0)
        power_l1 = int(_i32lw(_reg(regs, 0x0124), _reg(regs, 0x0125)) / 10.0)
        power_l2 = int(_i32lw(_reg(regs, 0x0132), _reg(regs, 0x0133)) / 10.0)
        power_l3 = int(_i32lw(_reg(regs, 0x0140), _reg(regs, 0x0141)) / 10.0)
        reactive_l1 = int(_i32lw(_reg(regs, 0x0128), _reg(regs, 0x0129)) / 10.0)
        reactive_l2 = int(_i32lw(_reg(regs, 0x0136), _reg(regs, 0x0137)) / 10.0)
        reactive_l3 = int(_i32lw(_reg(regs, 0x0144), _reg(regs, 0x0145)) / 10.0)
        apparent_l1 = int(_i32lw(_reg(regs, 0x0126), _reg(regs, 0x0127)) / 10.0)
        apparent_l2 = int(_i32lw(_reg(regs, 0x0134), _reg(regs, 0x0135)) / 10.0)
        apparent_l3 = int(_i32lw(_reg(regs, 0x0142), _reg(regs, 0x0143)) / 10.0)

        v1 = _i32lw(_reg(regs, 0x0120), _reg(regs, 0x0121)) / 10.0
        v2 = _i32lw(_reg(regs, 0x012E), _reg(regs, 0x012F)) / 10.0
        v3 = _i32lw(_reg(regs, 0x013C), _reg(regs, 0x013D)) / 10.0
        c1 = _i32lw(_reg(regs, 0x0122), _reg(regs, 0x0123)) / 1000.0
        c2 = _i32lw(_reg(regs, 0x0130), _reg(regs, 0x0131)) / 1000.0
        c3 = _i32lw(_reg(regs, 0x013E), _reg(regs, 0x013F)) / 1000.0

        pf_total = _i16(_reg(regs, 0x010D)) / 1000.0
        pf_l1 = _i16(_reg(regs, 0x012B)) / 1000.0
        pf_l2 = _i16(_reg(regs, 0x0139)) / 1000.0
        pf_l3 = _i16(_reg(regs, 0x0147)) / 1000.0
        freq_hz = _i16(_reg(regs, 0x0110)) / 10.0

        e_imp_total = _u32lw(_reg(regs, 0x0112), _reg(regs, 0x0113)) / 100.0
        e_exp_total = _u32lw(_reg(regs, 0x0116), _reg(regs, 0x0117)) / 100.0
        e_imp_l1 = _u32lw(_reg(regs, 0x014C), _reg(regs, 0x014D)) / 100.0
        e_imp_l2 = _u32lw(_reg(regs, 0x014E), _reg(regs, 0x014F)) / 100.0
        e_imp_l3 = _u32lw(_reg(regs, 0x0150), _reg(regs, 0x0151)) / 100.0

        return {
            "meter_power_w": power_w,
            "meter_power_l1_w": power_l1,
            "meter_power_l2_w": power_l2,
            "meter_power_l3_w": power_l3,
            "meter_reactive_power_l1_w": reactive_l1,
            "meter_reactive_power_l2_w": reactive_l2,
            "meter_reactive_power_l3_w": reactive_l3,
            "meter_reactive_power_total_w": reactive_l1 + reactive_l2 + reactive_l3,
            "meter_apparent_power_l1_w": apparent_l1,
            "meter_apparent_power_l2_w": apparent_l2,
            "meter_apparent_power_l3_w": apparent_l3,
            "meter_apparent_power_total_w": apparent_l1 + apparent_l2 + apparent_l3,
            "meter_power_factor_l1": pf_l1,
            "meter_power_factor_l2": pf_l2,
            "meter_power_factor_l3": pf_l3,
            "meter_power_factor_total": pf_total,
            "meter_frequency_hz": freq_hz,
            "meter_voltage_l1_v": v1,
            "meter_voltage_l2_v": v2,
            "meter_voltage_l3_v": v3,
            "meter_current_l1_a": c1,
            "meter_current_l2_a": c2,
            "meter_current_l3_a": c3,
            "meter_e_total_exp_kwh": e_exp_total,
            "meter_e_total_imp_kwh": e_imp_total,
            "meter_e_total_imp_l1_kwh": e_imp_l1,
            "meter_e_total_imp_l2_kwh": e_imp_l2,
            "meter_e_total_imp_l3_kwh": e_imp_l3,
        }


def _reg(registers: list[int], address: int) -> int:
    base = 0x0102
    idx = address - base
    if idx < 0 or idx >= len(registers):
        return 0
    return registers[idx]


def _i16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _i32lw(word0: int, word1: int) -> int:
    raw = ((word1 & 0xFFFF) << 16) | (word0 & 0xFFFF)
    if raw & 0x80000000:
        return raw - (1 << 32)
    return raw


def _u32lw(word0: int, word1: int) -> int:
    return ((word1 & 0xFFFF) << 16) | (word0 & 0xFFFF)
