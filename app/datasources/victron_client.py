from __future__ import annotations

import logging

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

from app.config import VictronConfig
from app.datasources.modbus_resilience import ModbusClientCircuitBreaker, read_modbus_payload_with_recovery

logger = logging.getLogger(__name__)

# Victron CCGX Modbus register addresses for battery data
# Unit ID 100 = System aggregates (read-only service data)
# Unit ID 0 = Primary battery service (com.victronenergy.battery)

# System battery data (Slave ID 100)
SYSTEM_BATTERY_VOLTAGE_REG = 840  # scale 10, V DC
SYSTEM_BATTERY_CURRENT_REG = 841  # scale 10, A DC
SYSTEM_BATTERY_POWER_REG = 842  # scale 1, W
SYSTEM_BATTERY_SOC_REG = 843  # scale 1, %
SYSTEM_BATTERY_STATE_REG = 844  # 0=idle, 1=charging, 2=discharging
SYSTEM_BATTERY_CONSUMED_AH_REG = 845  # scale -10, Ah
SYSTEM_BATTERY_TIME_TO_GO_REG = 846  # scale 0.01, s

# Battery service data (Slave ID 0, com.victronenergy.battery)
BATTERY_POWER_REG = 256  # int32, scale 1, W (256-257)
BATTERY_VOLTAGE_REG = 259  # scale 10, V DC
BATTERY_STARTER_VOLTAGE_REG = 260  # scale 10, V DC
BATTERY_CURRENT_REG = 261  # scale 10, A DC
BATTERY_TEMPERATURE_REG = 262  # scale 10, °C
BATTERY_MIDPOINT_VOLTAGE_REG = 263  # scale 10, V
BATTERY_MIDPOINT_DEVIATION_REG = 264  # scale 10, V
BATTERY_CONSUMED_AH_REG = 265  # scale -10, Ah
BATTERY_SOC_REG = 266  # scale 1, %
BATTERY_ALARM_REG = 267  # bitmask
BATTERY_TIME_TO_GO_REG = 303  # scale 0.01, s
BATTERY_STATE_OF_HEALTH_REG = 304  # scale 10, %
BATTERY_MAX_CHARGE_VOLTAGE_REG = 305  # scale 10, V
BATTERY_MIN_DISCHARGE_VOLTAGE_REG = 306  # scale 10, V
BATTERY_MAX_CHARGE_CURRENT_REG = 307  # scale 10, A
BATTERY_MAX_DISCHARGE_CURRENT_REG = 308  # scale 10, A
BATTERY_CAPACITY_REG = 309  # scale 10, Ah
BATTERY_STATE_REG = 1282  # 0=idle, 1=charging, 2=discharging
BATTERY_ERROR_REG = 1283  # error code


class VictronClient:
    def __init__(self, cfg: VictronConfig):
        self._cfg = cfg
        self._breaker = ModbusClientCircuitBreaker(
            "Victron",
            failure_threshold=2,
            cooldown_seconds=max(2.0, float(cfg.timeout) * 3.0),
        )

    def read(self) -> dict[str, float | int]:
        if not self._cfg.enabled:
            return {}

        return read_modbus_payload_with_recovery(
            source_name="Victron",
            create_client=self._build_client,
            read_once=self._read_once,
            breaker=self._breaker,
            retries=1,
        )

    def _build_client(self) -> ModbusTcpClient:
        return ModbusTcpClient(
            self._cfg.host,
            port=self._cfg.port,
            timeout=self._cfg.timeout,
            framer=FramerType.SOCKET,
        )

    def _read_once(self, client: ModbusTcpClient) -> dict[str, float | int]:
        # For Slave ID 100 (System aggregates), read the primary battery block
        if self._cfg.slave_id == 100:
            return self._read_system_battery(client)
        # For Slave ID 0 (Battery service), read detailed battery registers
        return self._read_battery_service(client)

    def _read_system_battery(self, client: ModbusTcpClient) -> dict[str, float | int]:
        """Read battery data from system aggregates (Slave ID 100)."""
        # Read system battery registers: 840-846
        rr = client.read_holding_registers(
            address=SYSTEM_BATTERY_VOLTAGE_REG,
            count=7,
            device_id=self._cfg.slave_id,
        )
        if rr.isError():
            logger.warning("Victron system battery read error")
            return {}

        regs = rr.registers
        data = {
            "battery_voltage_v": regs[0] / 10.0,  # reg 840
            "battery_current_a": _to_i16(regs[1]) / 10.0,  # reg 841
            "battery_power_w": _to_i16(regs[2]),  # reg 842
            "battery_soc_pct": max(0, min(100, regs[3])),  # reg 843
            "battery_state": regs[4],  # reg 844: 0=idle, 1=charging, 2=discharging
            "battery_consumed_ah": _to_i16(regs[5]) / -10.0,  # reg 845
            "battery_time_to_go_s": regs[6] / 100.0,  # reg 846
        }
        return data

    def _read_battery_service(self, client: ModbusTcpClient) -> dict[str, float | int]:
        """Read detailed battery data from battery service (Slave ID 0)."""
        # Read main battery registers block: 259-266
        rr = client.read_holding_registers(
            address=BATTERY_VOLTAGE_REG,
            count=8,
            device_id=self._cfg.slave_id,
        )
        if rr.isError():
            logger.warning("Victron battery service read error")
            return {}

        regs = rr.registers
        data = {
            "battery_voltage_v": regs[0] / 10.0,  # reg 259
            "battery_starter_voltage_v": regs[1] / 10.0,  # reg 260
            "battery_current_a": _to_i16(regs[2]) / 10.0,  # reg 261
            "battery_temperature_c": _to_i16(regs[3]) / 10.0,  # reg 262
            "battery_midpoint_voltage_v": regs[4] / 10.0,  # reg 263
            "battery_midpoint_deviation_v": regs[5] / 10.0,  # reg 264
            "battery_consumed_ah": _to_i16(regs[6]) / -10.0,  # reg 265
            "battery_soc_pct": max(0, min(100, regs[7])),  # reg 266
        }

        # Read battery power (32-bit int at 256-257)
        rr = client.read_holding_registers(
            address=BATTERY_POWER_REG,
            count=2,
            device_id=self._cfg.slave_id,
        )
        if not rr.isError():
            power_regs = rr.registers
            data["battery_power_w"] = _to_i32(power_regs[0], power_regs[1])  # reg 256-257

        # Read alarm and state (267, 1282)
        rr = client.read_holding_registers(
            address=BATTERY_ALARM_REG,
            count=1,
            device_id=self._cfg.slave_id,
        )
        if not rr.isError():
            data["battery_alarm"] = rr.registers[0]  # reg 267

        # Read extended registers: 303-309 and 1282-1283
        rr = client.read_holding_registers(
            address=BATTERY_TIME_TO_GO_REG,
            count=7,
            device_id=self._cfg.slave_id,
        )
        if not rr.isError():
            ext_regs = rr.registers
            data["battery_time_to_go_s"] = ext_regs[0] / 100.0  # reg 303
            data["battery_state_of_health_pct"] = ext_regs[1] / 10.0  # reg 304
            data["battery_max_charge_voltage_v"] = ext_regs[2] / 10.0  # reg 305
            data["battery_min_discharge_voltage_v"] = ext_regs[3] / 10.0  # reg 306
            data["battery_max_charge_current_a"] = ext_regs[4] / 10.0  # reg 307
            data["battery_max_discharge_current_a"] = ext_regs[5] / 10.0  # reg 308
            data["battery_capacity_ah"] = ext_regs[6] / 10.0  # reg 309

        # Read state and error (1282-1283)
        rr = client.read_holding_registers(
            address=BATTERY_STATE_REG,
            count=2,
            device_id=self._cfg.slave_id,
        )
        if not rr.isError():
            state_regs = rr.registers
            data["battery_state"] = state_regs[0]  # reg 1282: 0=idle, 1=charging, 2=discharge
            data["battery_error"] = state_regs[1]  # reg 1283

        return data


def _to_i16(val: int) -> int:
    """Convert unsigned 16-bit to signed integer."""
    if val & 0x8000:
        return val - 0x10000
    return val


def _to_i32(hi: int, lo: int) -> int:
    """Convert two 16-bit registers to signed 32-bit integer."""
    raw = ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)
    if raw & 0x80000000:
        return raw - (1 << 32)
    return raw
