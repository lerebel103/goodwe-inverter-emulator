from __future__ import annotations

import logging

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

from app.config import FroniusConfig
from app.datasources.modbus_resilience import ModbusClientCircuitBreaker, read_modbus_payload_with_recovery

logger = logging.getLogger(__name__)

# Fronius/SunSpec register map is fixed for this emulator and not user-configurable.
LEGACY_PV_POWER_REGISTER = 40083
LEGACY_PV_POWER_SF_REGISTER = 40084
LEGACY_DC_CURRENT_REGISTER = 40096
LEGACY_DC_CURRENT_SF_REGISTER = 40099
LEGACY_DC_VOLTAGE_REGISTER = 40097
LEGACY_DC_VOLTAGE_SF_REGISTER = 40100
LEGACY_DC_POWER_REGISTER = 40098
LEGACY_DC_POWER_SF_REGISTER = 40101

LEGACY_CHANNEL_REGISTERS = [
    (1, 41001, 41002, 41003),
    (2, 41011, 41012, 41013),
    (3, 41021, 41022, 41023),
    (4, 41031, 41032, 41033),
]

SUNSPEC_BASE_REGISTER = 40000
SUNSPEC_MODEL_160_ID = 160
SUNSPEC_MAX_MODELS_TO_SCAN = 64


class FroniusClient:
    def __init__(self, cfg: FroniusConfig):
        self._cfg = cfg
        self._breaker = ModbusClientCircuitBreaker(
            "Fronius",
            failure_threshold=2,
            cooldown_seconds=max(2.0, float(cfg.timeout) * 3.0),
        )

    def read(self) -> dict[str, int]:
        if not self._cfg.enabled:
            return {}

        return read_modbus_payload_with_recovery(
            source_name="Fronius",
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

    def _read_once(self, client: ModbusTcpClient) -> dict[str, int]:
        string_count = _effective_string_count(self._cfg)

        if self._cfg.sunspec_model_160_enabled:
            model_data = _read_sunspec_model_160(client, self._cfg.slave_id, string_count)
            if model_data:
                return model_data

        pv_power_w = _read_scaled_i16(
            client,
            LEGACY_PV_POWER_REGISTER,
            LEGACY_PV_POWER_SF_REGISTER,
            self._cfg.slave_id,
        )
        dc_power_w = _read_scaled_i16(
            client,
            LEGACY_DC_POWER_REGISTER,
            LEGACY_DC_POWER_SF_REGISTER,
            self._cfg.slave_id,
        )
        dc_voltage_v = _read_scaled_i16(
            client,
            LEGACY_DC_VOLTAGE_REGISTER,
            LEGACY_DC_VOLTAGE_SF_REGISTER,
            self._cfg.slave_id,
        )
        dc_current_a = _read_scaled_i16(
            client,
            LEGACY_DC_CURRENT_REGISTER,
            LEGACY_DC_CURRENT_SF_REGISTER,
            self._cfg.slave_id,
        )

        pv = _read_optional_channels(client, self._cfg.slave_id, string_count)

        if not any(int(pv[f"pv{i}_power_w"]) > 0 for i in range(1, string_count + 1)):
            total_dc = int(dc_power_w)
            for i in range(1, string_count + 1):
                base_p = int(total_dc / string_count)
                rem_p = total_dc - (base_p * string_count)
                power = base_p + (rem_p if i == string_count else 0)
                current = float(dc_current_a / string_count) if dc_current_a else 0.0
                pv.update(
                    {
                        f"pv{i}_power_w": max(0, power),
                        f"pv{i}_voltage_v": float(dc_voltage_v),
                        f"pv{i}_current_a": max(0.0, current),
                    }
                )

        return {
            "pv_power_w": int(pv_power_w),
            **pv,
        }


def _to_i16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _read_scaled_i16(client: ModbusTcpClient, value_register: int, sf_register: int, slave_id: int) -> float:
    rr = client.read_holding_registers(address=value_register, count=1, device_id=slave_id)
    if rr.isError():
        return 0.0

    sf_rr = client.read_holding_registers(address=sf_register, count=1, device_id=slave_id)
    if sf_rr.isError():
        return 0.0

    raw = _to_i16(rr.registers[0])
    sf = _to_i16(sf_rr.registers[0])
    return float(raw * (10**sf))


def _read_optional_channels(client: ModbusTcpClient, slave_id: int, string_count: int) -> dict[str, float | int]:
    out: dict[str, float | int] = {
        "pv1_voltage_v": 0.0,
        "pv1_current_a": 0.0,
        "pv1_power_w": 0,
        "pv2_voltage_v": 0.0,
        "pv2_current_a": 0.0,
        "pv2_power_w": 0,
        "pv3_voltage_v": 0.0,
        "pv3_current_a": 0.0,
        "pv3_power_w": 0,
        "pv4_voltage_v": 0.0,
        "pv4_current_a": 0.0,
        "pv4_power_w": 0,
    }

    for idx, v_reg, i_reg, p_reg in LEGACY_CHANNEL_REGISTERS:
        if idx > string_count:
            continue
        rr = client.read_holding_registers(address=v_reg, count=1, device_id=slave_id)
        if not rr.isError():
            out[f"pv{idx}_voltage_v"] = _to_i16(rr.registers[0]) / 10.0

        rr = client.read_holding_registers(address=i_reg, count=1, device_id=slave_id)
        if not rr.isError():
            out[f"pv{idx}_current_a"] = _to_i16(rr.registers[0]) / 10.0

        rr = client.read_holding_registers(address=p_reg, count=1, device_id=slave_id)
        if not rr.isError():
            out[f"pv{idx}_power_w"] = _to_i16(rr.registers[0])

    return out


def _read_sunspec_model_160(
    client: ModbusTcpClient,
    slave_id: int,
    string_count: int,
) -> dict[str, float | int]:
    model = _find_sunspec_model(
        client,
        slave_id,
        base_register=SUNSPEC_BASE_REGISTER,
        model_id=SUNSPEC_MODEL_160_ID,
        max_models=SUNSPEC_MAX_MODELS_TO_SCAN,
    )
    if model is None:
        return {}

    model_start, model_len = model
    regs = _read_register_block(client, model_start, model_len, slave_id)
    if len(regs) < 8:
        return {}

    dca_sf = _to_i16(regs[0])
    dcv_sf = _to_i16(regs[1])
    dcw_sf = _to_i16(regs[2])
    module_count = max(0, int(regs[6]))

    module_len = 20
    modules_available = max(0, (model_len - 8) // module_len)
    modules_to_parse = min(module_count, modules_available, string_count, 4)

    out: dict[str, float | int] = {
        "pv1_voltage_v": 0.0,
        "pv1_current_a": 0.0,
        "pv1_power_w": 0,
        "pv2_voltage_v": 0.0,
        "pv2_current_a": 0.0,
        "pv2_power_w": 0,
        "pv3_voltage_v": 0.0,
        "pv3_current_a": 0.0,
        "pv3_power_w": 0,
        "pv4_voltage_v": 0.0,
        "pv4_current_a": 0.0,
        "pv4_power_w": 0,
        "pv_power_w": 0,
    }

    total_power = 0
    for index in range(modules_to_parse):
        base = 8 + (index * module_len)
        if base + 11 >= len(regs):
            break

        dca_raw = regs[base + 9]
        dcv_raw = regs[base + 10]
        dcw_raw = regs[base + 11]

        current_a = float(dca_raw * (10**dca_sf))
        voltage_v = float(dcv_raw * (10**dcv_sf))
        power_w = int(dcw_raw * (10**dcw_sf))

        channel = index + 1
        out[f"pv{channel}_current_a"] = max(0.0, current_a)
        out[f"pv{channel}_voltage_v"] = max(0.0, voltage_v)
        out[f"pv{channel}_power_w"] = max(0, power_w)
        total_power += max(0, power_w)

    out["pv_power_w"] = total_power
    return out


def _find_sunspec_model(
    client: ModbusTcpClient,
    slave_id: int,
    base_register: int,
    model_id: int,
    max_models: int,
) -> tuple[int, int] | None:
    # Some devices expose the SunSpec base at 40000, others at 40001.
    for candidate_base in (base_register, base_register + 1):
        sig = _read_register_block(client, candidate_base, 2, slave_id)
        if len(sig) != 2 or sig[0] != 0x5375 or sig[1] != 0x6E53:
            continue

        header_addr = candidate_base + 2
        for _ in range(max_models):
            header = _read_register_block(client, header_addr, 2, slave_id)
            if len(header) != 2:
                break
            mid = header[0]
            mlen = header[1]
            if mid == 0xFFFF:
                break
            if mlen <= 0:
                break
            if mid == model_id:
                return (header_addr + 2, mlen)

            header_addr += 2 + mlen

    return None


def _read_register_block(client: ModbusTcpClient, address: int, count: int, slave_id: int) -> list[int]:
    rr = client.read_holding_registers(address=address, count=count, device_id=slave_id)
    if rr.isError():
        return []
    return rr.registers


def _effective_string_count(cfg: FroniusConfig) -> int:
    return max(1, min(int(cfg.pv_string_count), 4))
