from __future__ import annotations

import logging
import math
import struct

from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient

from app.config import FroniusConfig
from app.datasources.modbus_resilience import ModbusClientCircuitBreaker, PersistentModbusSession

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
SUNSPEC_MODEL_101_ID = 101
SUNSPEC_MODEL_111_ID = 111
SUNSPEC_MODEL_103_ID = 103
SUNSPEC_MODEL_113_ID = 113
SUNSPEC_MODEL_160_ID = 160
SUNSPEC_MAX_MODELS_TO_SCAN = 64
SUNSPEC_MIN_SCALE_FACTOR = -6
SUNSPEC_MAX_SCALE_FACTOR = 6
_LOGGED_INVERTER_MODELS: set[int] = set()


class FroniusClient:
    def __init__(self, cfg: FroniusConfig):
        self._cfg = cfg
        self._breaker = ModbusClientCircuitBreaker(
            "Fronius",
            failure_threshold=2,
            cooldown_seconds=max(2.0, float(cfg.timeout) * 3.0),
        )
        self._model_index_cache: dict[int, tuple[int, int]] | None = None
        self._session = PersistentModbusSession(
            source_name="Fronius",
            create_client=self._build_client,
            breaker=self._breaker,
            retries=1,
        )

    def read(self) -> dict[str, int]:
        if not self._cfg.enabled:
            return {}

        return self._session.read(self._read_once)

    def _build_client(self) -> ModbusTcpClient:
        return ModbusTcpClient(
            self._cfg.host,
            port=self._cfg.port,
            timeout=self._cfg.timeout,
            framer=FramerType.SOCKET,
        )

    def _read_once(self, client: ModbusTcpClient) -> dict[str, int]:
        string_count = _effective_string_count(self._cfg)
        model_index = self._get_model_index(client)
        inverter_ac = _read_sunspec_inverter_ac_power(client, self._cfg.slave_id, model_index)
        if not inverter_ac and model_index:
            logger.debug(
                "Fronius SunSpec model 101/103 not found in model table (available models: %s)",
                sorted(model_index.keys()),
            )

        model_data: dict[str, float | int] = {}
        if self._cfg.sunspec_model_160_enabled:
            model_data = _read_sunspec_model_160(client, self._cfg.slave_id, string_count, model_index)

        # If cached SunSpec model offsets become invalid (firmware restart/map shift),
        # force one rescan and retry once before falling back to legacy reads.
        if self._model_index_cache and not inverter_ac and not model_data:
            refreshed = _scan_sunspec_model_index(client, self._cfg.slave_id)
            if refreshed:
                self._model_index_cache = refreshed
                model_index = refreshed
                inverter_ac = _read_sunspec_inverter_ac_power(client, self._cfg.slave_id, model_index)
                if self._cfg.sunspec_model_160_enabled:
                    model_data = _read_sunspec_model_160(client, self._cfg.slave_id, string_count, model_index)

        if model_data:
            return {
                **model_data,
                **inverter_ac,
            }

        legacy_block = _read_register_block(client, LEGACY_PV_POWER_REGISTER, 19, self._cfg.slave_id)
        if len(legacy_block) == 19:
            pv_power_w = _read_scaled_i16_from_block(
                base_register=LEGACY_PV_POWER_REGISTER,
                block=legacy_block,
                value_register=LEGACY_PV_POWER_REGISTER,
                sf_register=LEGACY_PV_POWER_SF_REGISTER,
            )
            dc_power_w = _read_scaled_i16_from_block(
                base_register=LEGACY_PV_POWER_REGISTER,
                block=legacy_block,
                value_register=LEGACY_DC_POWER_REGISTER,
                sf_register=LEGACY_DC_POWER_SF_REGISTER,
            )
            dc_voltage_v = _read_scaled_i16_from_block(
                base_register=LEGACY_PV_POWER_REGISTER,
                block=legacy_block,
                value_register=LEGACY_DC_VOLTAGE_REGISTER,
                sf_register=LEGACY_DC_VOLTAGE_SF_REGISTER,
            )
            dc_current_a = _read_scaled_i16_from_block(
                base_register=LEGACY_PV_POWER_REGISTER,
                block=legacy_block,
                value_register=LEGACY_DC_CURRENT_REGISTER,
                sf_register=LEGACY_DC_CURRENT_SF_REGISTER,
            )
        else:
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
            **inverter_ac,
        }

    def _get_model_index(self, client: ModbusTcpClient) -> dict[int, tuple[int, int]]:
        # Do not permanently cache an empty index; upstream SunSpec tables may be
        # temporarily unavailable during startup and become readable later.
        if self._model_index_cache:
            return self._model_index_cache

        self._model_index_cache = _scan_sunspec_model_index(client, self._cfg.slave_id)
        return self._model_index_cache


def _to_i16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _read_scaled_from_model_i16(regs: list[int], value_index: int, sf_index: int) -> float:
    if value_index >= len(regs) or sf_index >= len(regs):
        return 0.0

    raw = _to_i16(regs[value_index])
    sf = _to_i16(regs[sf_index])

    # SunSpec int16 "not implemented" sentinel.
    if raw == -32768 or sf == -32768:
        return 0.0

    if sf < SUNSPEC_MIN_SCALE_FACTOR or sf > SUNSPEC_MAX_SCALE_FACTOR:
        return 0.0

    try:
        return float(raw * (10**sf))
    except OverflowError:
        return 0.0


def _read_scaled_from_model_u16(regs: list[int], value_index: int, sf_index: int) -> float:
    if value_index >= len(regs) or sf_index >= len(regs):
        return 0.0

    raw_u16 = regs[value_index] & 0xFFFF
    sf = _to_i16(regs[sf_index])

    # SunSpec uint16 and sunssf "not implemented" sentinels.
    if raw_u16 == 0xFFFF or sf == -32768:
        return 0.0

    if sf < SUNSPEC_MIN_SCALE_FACTOR or sf > SUNSPEC_MAX_SCALE_FACTOR:
        return 0.0

    try:
        return float(raw_u16 * (10**sf))
    except OverflowError:
        return 0.0


def _read_scaled_i16(client: ModbusTcpClient, value_register: int, sf_register: int, slave_id: int) -> float:
    rr = client.read_holding_registers(address=value_register, count=1, device_id=slave_id)
    if rr.isError():
        return 0.0

    sf_rr = client.read_holding_registers(address=sf_register, count=1, device_id=slave_id)
    if sf_rr.isError():
        return 0.0

    raw = _to_i16(rr.registers[0])
    sf = _to_i16(sf_rr.registers[0])
    if sf < SUNSPEC_MIN_SCALE_FACTOR or sf > SUNSPEC_MAX_SCALE_FACTOR:
        return 0.0

    try:
        return float(raw * (10**sf))
    except OverflowError:
        return 0.0


def _read_scaled_i16_from_block(
    *,
    base_register: int,
    block: list[int],
    value_register: int,
    sf_register: int,
) -> float:
    value_idx = value_register - base_register
    sf_idx = sf_register - base_register
    if value_idx < 0 or sf_idx < 0 or value_idx >= len(block) or sf_idx >= len(block):
        return 0.0

    raw = _to_i16(block[value_idx])
    sf = _to_i16(block[sf_idx])
    if sf < SUNSPEC_MIN_SCALE_FACTOR or sf > SUNSPEC_MAX_SCALE_FACTOR:
        return 0.0

    try:
        return float(raw * (10**sf))
    except OverflowError:
        return 0.0


def _read_sunspec_inverter_ac_power(
    client: ModbusTcpClient,
    slave_id: int,
    model_index: dict[int, tuple[int, int]] | None = None,
) -> dict[str, int]:
    # Prefer 3-phase inverter models (113/103), then fallback to single-phase (111/101).
    if model_index is None:
        model_index = _scan_sunspec_model_index(client, slave_id)

    model_113 = model_index.get(SUNSPEC_MODEL_113_ID)
    if model_113 is not None:
        model_start, model_len = model_113
        model_id = SUNSPEC_MODEL_113_ID
        _log_inverter_model_once(model_id, model_start, model_len)
        regs = _read_register_block(client, model_start, model_len, slave_id)
        if regs:
            current_l1 = _read_f32_from_model(regs, value_index=2)
            current_l2 = _read_f32_from_model(regs, value_index=4)
            current_l3 = _read_f32_from_model(regs, value_index=6)
            voltage_l1 = _read_f32_from_model(regs, value_index=14)
            voltage_l2 = _read_f32_from_model(regs, value_index=16)
            voltage_l3 = _read_f32_from_model(regs, value_index=18)
            active_total = int(_read_f32_from_model(regs, value_index=20))
            apparent_total = int(_read_f32_from_model(regs, value_index=24))
            reactive_total = int(_read_f32_from_model(regs, value_index=26))
            power_factor = _derive_power_factor(
                active_total,
                apparent_total,
                _read_f32_from_model(regs, value_index=28),
            )
            temperature_air = _read_f32_from_model(regs, value_index=38)
            temperature_radiator = _read_f32_from_model(regs, value_index=40)
            temperature_module = _read_f32_from_model(regs, value_index=42)
            phase_weights = [
                max(0.0, current_l1 * voltage_l1),
                max(0.0, current_l2 * voltage_l2),
                max(0.0, current_l3 * voltage_l3),
            ]
            active_l1, active_l2, active_l3 = _split_total_by_weights(active_total, phase_weights)
            apparent_l1, apparent_l2, apparent_l3 = _split_total_by_weights(apparent_total, phase_weights)
            reactive_l1, reactive_l2, reactive_l3 = _split_total_by_weights(reactive_total, phase_weights)
            return {
                "inverter_current_l1_a": current_l1,
                "inverter_current_l2_a": current_l2,
                "inverter_current_l3_a": current_l3,
                "inverter_voltage_l1_v": voltage_l1,
                "inverter_voltage_l2_v": voltage_l2,
                "inverter_voltage_l3_v": voltage_l3,
                "inverter_frequency_hz": _read_f32_from_model(regs, value_index=22),
                "inverter_active_power_w": active_total,
                "inverter_power_l1_w": active_l1,
                "inverter_power_l2_w": active_l2,
                "inverter_power_l3_w": active_l3,
                "inverter_apparent_power_va": apparent_total,
                "inverter_apparent_power_l1_va": apparent_l1,
                "inverter_apparent_power_l2_va": apparent_l2,
                "inverter_apparent_power_l3_va": apparent_l3,
                "inverter_reactive_power_var": reactive_total,
                "inverter_reactive_power_l1_var": reactive_l1,
                "inverter_reactive_power_l2_var": reactive_l2,
                "inverter_reactive_power_l3_var": reactive_l3,
                "inverter_power_factor": power_factor,
                "inverter_temperature_air_c": temperature_air,
                "inverter_temperature_module_c": temperature_module,
                "inverter_temperature_radiator_c": temperature_radiator,
            }

    model_103 = model_index.get(SUNSPEC_MODEL_103_ID)
    if model_103 is not None:
        model_start, model_len = model_103
        model_id = SUNSPEC_MODEL_103_ID
        _log_inverter_model_once(model_id, model_start, model_len)
        regs = _read_register_block(client, model_start, model_len, slave_id)
        if regs:
            apparent_total = int(_read_scaled_from_model_u16(regs, value_index=16, sf_index=20))
            active_total = int(_read_scaled_from_model_i16(regs, value_index=9, sf_index=13))
            reactive_total = int(_read_scaled_from_model_i16(regs, value_index=21, sf_index=25))
            return {
                "inverter_current_l1_a": _read_scaled_from_model_u16(regs, value_index=1, sf_index=4),
                "inverter_current_l2_a": _read_scaled_from_model_u16(regs, value_index=2, sf_index=4),
                "inverter_current_l3_a": _read_scaled_from_model_u16(regs, value_index=3, sf_index=4),
                "inverter_voltage_l1_v": _read_scaled_from_model_u16(regs, value_index=5, sf_index=8),
                "inverter_voltage_l2_v": _read_scaled_from_model_u16(regs, value_index=6, sf_index=8),
                "inverter_voltage_l3_v": _read_scaled_from_model_u16(regs, value_index=7, sf_index=8),
                "inverter_frequency_hz": _read_scaled_from_model_u16(regs, value_index=14, sf_index=15),
                "inverter_active_power_w": active_total,
                "inverter_power_l1_w": int(_read_scaled_from_model_i16(regs, value_index=10, sf_index=13)),
                "inverter_power_l2_w": int(_read_scaled_from_model_i16(regs, value_index=11, sf_index=13)),
                "inverter_power_l3_w": int(_read_scaled_from_model_i16(regs, value_index=12, sf_index=13)),
                "inverter_apparent_power_va": apparent_total,
                "inverter_apparent_power_l1_va": int(_read_scaled_from_model_u16(regs, value_index=17, sf_index=20)),
                "inverter_apparent_power_l2_va": int(_read_scaled_from_model_u16(regs, value_index=18, sf_index=20)),
                "inverter_apparent_power_l3_va": int(_read_scaled_from_model_u16(regs, value_index=19, sf_index=20)),
                "inverter_reactive_power_var": reactive_total,
                "inverter_reactive_power_l1_var": int(_read_scaled_from_model_i16(regs, value_index=22, sf_index=25)),
                "inverter_reactive_power_l2_var": int(_read_scaled_from_model_i16(regs, value_index=23, sf_index=25)),
                "inverter_reactive_power_l3_var": int(_read_scaled_from_model_i16(regs, value_index=24, sf_index=25)),
                "inverter_power_factor": _derive_power_factor(
                    active_total,
                    apparent_total,
                    _read_scaled_from_model_i16(regs, value_index=20, sf_index=21),
                ),
                "inverter_temperature_air_c": _read_scaled_from_model_i16(regs, value_index=31, sf_index=35),
                "inverter_temperature_module_c": _read_scaled_from_model_i16(regs, value_index=33, sf_index=35),
                "inverter_temperature_radiator_c": _read_scaled_from_model_i16(regs, value_index=32, sf_index=35),
            }

    model_111 = model_index.get(SUNSPEC_MODEL_111_ID)
    if model_111 is not None:
        model_start, model_len = model_111
        model_id = SUNSPEC_MODEL_111_ID
        _log_inverter_model_once(model_id, model_start, model_len)
        regs = _read_register_block(client, model_start, model_len, slave_id)
        if regs:
            active_total = int(_read_f32_from_model(regs, value_index=20))
            apparent_total = int(_read_f32_from_model(regs, value_index=24))
            reactive_total = int(_read_f32_from_model(regs, value_index=26))
            return {
                "inverter_current_l1_a": _read_f32_from_model(regs, value_index=2),
                "inverter_voltage_l1_v": _read_f32_from_model(regs, value_index=14),
                "inverter_frequency_hz": _read_f32_from_model(regs, value_index=22),
                "inverter_active_power_w": active_total,
                "inverter_power_l1_w": active_total,
                "inverter_apparent_power_va": apparent_total,
                "inverter_apparent_power_l1_va": apparent_total,
                "inverter_reactive_power_var": reactive_total,
                "inverter_reactive_power_l1_var": reactive_total,
                "inverter_power_factor": _derive_power_factor(
                    active_total,
                    apparent_total,
                    _read_f32_from_model(regs, value_index=28),
                ),
                "inverter_temperature_air_c": _read_f32_from_model(regs, value_index=38),
                "inverter_temperature_module_c": _read_f32_from_model(regs, value_index=42),
                "inverter_temperature_radiator_c": _read_f32_from_model(regs, value_index=40),
            }

    model_101 = model_index.get(SUNSPEC_MODEL_101_ID)
    if model_101 is not None:
        model_start, model_len = model_101
        model_id = SUNSPEC_MODEL_101_ID
        _log_inverter_model_once(model_id, model_start, model_len)
        regs = _read_register_block(client, model_start, model_len, slave_id)
        if regs:
            apparent_total = int(_read_scaled_from_model_u16(regs, value_index=8, sf_index=9))
            active_total = int(_read_scaled_from_model_i16(regs, value_index=4, sf_index=5))
            reactive_total = int(_read_scaled_from_model_i16(regs, value_index=10, sf_index=11))
            return {
                "inverter_current_l1_a": _read_scaled_from_model_u16(regs, value_index=0, sf_index=1),
                "inverter_voltage_l1_v": _read_scaled_from_model_u16(regs, value_index=2, sf_index=3),
                "inverter_frequency_hz": _read_scaled_from_model_u16(regs, value_index=6, sf_index=7),
                "inverter_active_power_w": active_total,
                "inverter_power_l1_w": active_total,
                "inverter_apparent_power_va": apparent_total,
                "inverter_apparent_power_l1_va": apparent_total,
                "inverter_reactive_power_var": reactive_total,
                "inverter_reactive_power_l1_var": reactive_total,
                "inverter_power_factor": _derive_power_factor(
                    active_total,
                    apparent_total,
                    _read_scaled_from_model_i16(regs, value_index=20, sf_index=21),
                ),
                "inverter_temperature_air_c": _read_scaled_from_model_i16(regs, value_index=31, sf_index=35),
                "inverter_temperature_module_c": _read_scaled_from_model_i16(regs, value_index=33, sf_index=35),
                "inverter_temperature_radiator_c": _read_scaled_from_model_i16(regs, value_index=32, sf_index=35),
            }

    return {}


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
        rr = client.read_holding_registers(address=v_reg, count=3, device_id=slave_id)
        if not rr.isError() and len(rr.registers) >= 3:
            out[f"pv{idx}_voltage_v"] = _to_i16(rr.registers[0]) / 10.0
            out[f"pv{idx}_current_a"] = _to_i16(rr.registers[1]) / 10.0
            out[f"pv{idx}_power_w"] = _to_i16(rr.registers[2])

    return out


def _read_f32_from_model(regs: list[int], value_index: int) -> float:
    if value_index < 0 or value_index + 1 >= len(regs):
        return 0.0

    hi = regs[value_index] & 0xFFFF
    lo = regs[value_index + 1] & 0xFFFF
    value = struct.unpack(">f", struct.pack(">HH", hi, lo))[0]
    if not math.isfinite(value):
        return 0.0
    return float(value)


def _split_total_by_weights(total: int, weights: list[float]) -> tuple[int, int, int]:
    if len(weights) != 3:
        return 0, 0, total

    clamped = [max(0.0, float(w)) for w in weights]
    weight_sum = sum(clamped)
    if weight_sum <= 0.0:
        base = int(total / 3)
        remainder = total - (base * 3)
        return base, base, base + remainder

    l1 = int(total * (clamped[0] / weight_sum))
    l2 = int(total * (clamped[1] / weight_sum))
    l3 = total - l1 - l2
    return l1, l2, l3


def _clamp_power_factor(value: float) -> float:
    if not math.isfinite(value):
        return 1.0
    return max(-1.0, min(1.0, float(value)))


def _derive_power_factor(active_power_w: int, apparent_power_va: int, candidate: float) -> float:
    if abs(candidate) > 0.0:
        return _clamp_power_factor(candidate)

    if apparent_power_va == 0:
        return 1.0

    return _clamp_power_factor(float(active_power_w) / float(apparent_power_va))


def _log_inverter_model_once(model_id: int, model_start: int, model_len: int) -> None:
    if model_id in _LOGGED_INVERTER_MODELS:
        return

    _LOGGED_INVERTER_MODELS.add(model_id)
    logger.warning(
        "Fronius inverter AC SunSpec model detected: id=%s start=%s len=%s",
        model_id,
        model_start,
        model_len,
    )


def _read_sunspec_model_160(
    client: ModbusTcpClient,
    slave_id: int,
    string_count: int,
    model_index: dict[int, tuple[int, int]] | None = None,
) -> dict[str, float | int]:
    if model_index is None:
        model_index = _scan_sunspec_model_index(client, slave_id)

    model = model_index.get(SUNSPEC_MODEL_160_ID)
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

        # SunSpec uint16 "not implemented" sentinel — treat as zero rather than
        # producing a large spurious value after scale factor is applied.
        _U16_NI = 0xFFFF
        current_a = float(dca_raw * (10**dca_sf)) if dca_raw != _U16_NI else 0.0
        voltage_v = float(dcv_raw * (10**dcv_sf)) if dcv_raw != _U16_NI else 0.0
        power_w = int(dcw_raw * (10**dcw_sf)) if dcw_raw != _U16_NI else 0

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


def _scan_sunspec_model_index(
    client: ModbusTcpClient,
    slave_id: int,
    *,
    base_register: int = SUNSPEC_BASE_REGISTER,
    max_models: int = SUNSPEC_MAX_MODELS_TO_SCAN,
) -> dict[int, tuple[int, int]]:
    for candidate_base in (base_register, base_register + 1):
        sig = _read_register_block(client, candidate_base, 2, slave_id)
        if len(sig) != 2 or sig[0] != 0x5375 or sig[1] != 0x6E53:
            continue

        models: dict[int, tuple[int, int]] = {}
        header_addr = candidate_base + 2
        for _ in range(max_models):
            header = _read_register_block(client, header_addr, 2, slave_id)
            if len(header) != 2:
                break

            mid = header[0]
            mlen = header[1]
            if mid == 0xFFFF or mlen <= 0:
                break

            models[mid] = (header_addr + 2, mlen)
            header_addr += 2 + mlen

        return models

    return {}


def _read_register_block(client: ModbusTcpClient, address: int, count: int, slave_id: int) -> list[int]:
    rr = client.read_holding_registers(address=address, count=count, device_id=slave_id)
    if rr.isError():
        return []
    return rr.registers


def _effective_string_count(cfg: FroniusConfig) -> int:
    return max(1, min(int(cfg.pv_string_count), 4))
