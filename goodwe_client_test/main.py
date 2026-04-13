from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime

import goodwe


def _pick(data: dict[str, object], *keys: str, default=None):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _read_external_model_name(inverter) -> str:
    """Best-effort low-level read of register 35060 (16 regs, ASCII)."""
    try:
        cmd = inverter._read_command(35060, 16)
        response = await inverter._read_from_socket(cmd)
        payload = response.response_data()
        if not payload:
            return ""
        return bytes(payload[:32]).decode("ascii", errors="ignore").rstrip(" \x00")
    except Exception:
        return ""


def _split_total_weighted(total: int, weights: tuple[float, float, float]) -> tuple[int, int, int]:
    w1, w2, w3 = (max(0.0, float(w)) for w in weights)
    s = w1 + w2 + w3
    if s <= 0.0:
        base = int(total / 3)
        rem = total - (base * 3)
        return base, base, base + rem

    p1 = int(total * (w1 / s))
    p2 = int(total * (w2 / s))
    p3 = total - p1 - p2
    return p1, p2, p3


def _decode_from_sdk(
    data: dict[str, object], model_name: str | None, external_model_name: str | None
) -> dict[str, object]:
    ts = _pick(data, "timestamp", "timestamp_utc")
    if isinstance(ts, datetime):
        year_2digit = ts.year % 100
        month = ts.month
    elif isinstance(ts, str):
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00").replace(" ", "T"))
        year_2digit = parsed.year % 100
        month = parsed.month
    else:
        year_2digit = 0
        month = 0

    rtc_raw = ((year_2digit & 0xFF) << 8) | (month & 0xFF)

    l1_voltage = _pick(data, "vgrid1", "vgrid", "vac1")
    l2_voltage = _pick(data, "vgrid2", "vac2")
    l3_voltage = _pick(data, "vgrid3", "vac3")

    l1_current = _pick(data, "igrid1", "iac1", "igrid")
    l2_current = _pick(data, "igrid2", "iac2")
    l3_current = _pick(data, "igrid3", "iac3")

    l1_frequency = _pick(data, "fgrid")
    l2_frequency = _pick(data, "fgrid2")
    l3_frequency = _pick(data, "fgrid3")

    inv_l1_active = _pick(data, "pgrid1", "pgrid")
    inv_l2_active = _pick(data, "pgrid2")
    inv_l3_active = _pick(data, "pgrid3")

    inv_l1_reactive = _pick(data, "reactive_power1")
    inv_l2_reactive = _pick(data, "reactive_power2")
    inv_l3_reactive = _pick(data, "reactive_power3")
    inv_total_reactive = _pick(data, "reactive_power")

    inv_l1_apparent = _pick(data, "apparent_power1")
    inv_l2_apparent = _pick(data, "apparent_power2")
    inv_l3_apparent = _pick(data, "apparent_power3")
    inv_total_apparent = _pick(data, "apparent_power")
    inv_power_factor = _pick(data, "power_factor")
    inv_temp_air = _pick(data, "temperature_air")
    inv_temp_module = _pick(data, "temperature_module")
    inv_temp_radiator = _pick(data, "temperature")

    meter_l1_active = _pick(data, "meter_active_power1")
    meter_l2_active = _pick(data, "meter_active_power2")
    meter_l3_active = _pick(data, "meter_active_power3")
    meter_freq = _pick(data, "meter_freq")
    meter_pf_l1 = _pick(data, "meter_power_factor1")
    meter_pf_l2 = _pick(data, "meter_power_factor2")
    meter_pf_l3 = _pick(data, "meter_power_factor3")
    meter_pf_total = _pick(data, "meter_power_factor")
    meter_v1 = _pick(data, "meter_voltage1")
    meter_v2 = _pick(data, "meter_voltage2")
    meter_v3 = _pick(data, "meter_voltage3")
    meter_i1 = _pick(data, "meter_current1")
    meter_i2 = _pick(data, "meter_current2")
    meter_i3 = _pick(data, "meter_current3")

    # Some inverter/SDK combinations expose only total VA/VAr while phase channels
    # can be missing/zero. Reconstruct per-phase values from total using active
    # phase magnitudes as weights so UI output remains physically plausible.
    active_weights = (
        abs(_as_float(inv_l1_active, 0.0)),
        abs(_as_float(inv_l2_active, 0.0)),
        abs(_as_float(inv_l3_active, 0.0)),
    )

    inv_l1_apparent_i = _as_int(inv_l1_apparent) if inv_l1_apparent is not None else None
    inv_l2_apparent_i = _as_int(inv_l2_apparent) if inv_l2_apparent is not None else None
    inv_l3_apparent_i = _as_int(inv_l3_apparent) if inv_l3_apparent is not None else None
    inv_total_apparent_i = _as_int(inv_total_apparent) if inv_total_apparent is not None else None

    if (
        inv_total_apparent_i not in (None, 0)
        and (
            (inv_l2_apparent_i in (None, 0) and inv_l3_apparent_i in (None, 0))
            or (inv_l1_apparent_i == inv_l2_apparent_i == inv_l3_apparent_i)
        )
    ):
        inv_l1_apparent_i, inv_l2_apparent_i, inv_l3_apparent_i = _split_total_weighted(
            inv_total_apparent_i, active_weights
        )

    inv_l1_reactive_i = _as_int(inv_l1_reactive) if inv_l1_reactive is not None else None
    inv_l2_reactive_i = _as_int(inv_l2_reactive) if inv_l2_reactive is not None else None
    inv_l3_reactive_i = _as_int(inv_l3_reactive) if inv_l3_reactive is not None else None
    inv_total_reactive_i = _as_int(inv_total_reactive) if inv_total_reactive is not None else None

    if (
        inv_total_reactive_i not in (None, 0)
        and (
            (inv_l2_reactive_i in (None, 0) and inv_l3_reactive_i in (None, 0))
            or (inv_l1_reactive_i == inv_l2_reactive_i == inv_l3_reactive_i)
        )
    ):
        inv_l1_reactive_i, inv_l2_reactive_i, inv_l3_reactive_i = _split_total_weighted(
            inv_total_reactive_i, active_weights
        )

    l1_reactive = _pick(data, "meter_reactive_power1")
    l2_reactive = _pick(data, "meter_reactive_power2")
    l3_reactive = _pick(data, "meter_reactive_power3")
    total_reactive = _pick(data, "meter_reactive_power_total", "reactive_power_total")

    l1_apparent = _pick(data, "meter_apparent_power1")
    l2_apparent = _pick(data, "meter_apparent_power2")
    l3_apparent = _pick(data, "meter_apparent_power3")
    total_apparent = _pick(data, "meter_apparent_power_total")

    return {
        "device": {
            "model_name": model_name or _pick(data, "model_name", default=""),
            "external_model_name": external_model_name
            or _pick(data, "external_model_name", default=""),
            "rtc": {
                "year_2digit": year_2digit,
                "month": month,
                "raw": rtc_raw,
            },
        },
        "pv": {
            "pv1_voltage_v": _as_float(_pick(data, "vpv1")),
            "pv1_current_a": _as_float(_pick(data, "ipv1")),
            "pv1_power_w": _as_int(_pick(data, "ppv1")),
            "pv2_voltage_v": _as_float(_pick(data, "vpv2")),
            "pv2_current_a": _as_float(_pick(data, "ipv2")),
            "pv2_power_w": _as_int(_pick(data, "ppv2")),
            "pv3_power_w": _as_int(_pick(data, "ppv3")),
            "pv4_power_w": _as_int(_pick(data, "ppv4")),
            "total_w": _as_int(_pick(data, "ppv", "ppv_total")),
        },
        "battery": {
            "voltage_v": _as_float(_pick(data, "vbattery1", "battery_voltage")),
            "voltage_2_v": _as_float(_pick(data, "vbattery2", default=0.0)),
            "current_a": _as_float(_pick(data, "ibattery1", "battery_current")),
            "power_w": _as_int(_pick(data, "pbattery1", "battery_power")),
        },
        "inverter_ac": {
            "active_power_w": {
                "l1": _as_int(inv_l1_active) if inv_l1_active is not None else None,
                "l2": _as_int(inv_l2_active) if inv_l2_active is not None else None,
                "l3": _as_int(inv_l3_active) if inv_l3_active is not None else None,
                "total": _as_int(_pick(data, "active_power")),
            },
            "reactive_power_var": {
                "l1": inv_l1_reactive_i,
                "l2": inv_l2_reactive_i,
                "l3": inv_l3_reactive_i,
                "total": inv_total_reactive_i,
            },
            "apparent_power_va": {
                "l1": inv_l1_apparent_i,
                "l2": inv_l2_apparent_i,
                "l3": inv_l3_apparent_i,
                "total": inv_total_apparent_i,
            },
            "voltage_v": {
                "l1": _as_float(l1_voltage) if l1_voltage is not None else None,
                "l2": _as_float(l2_voltage) if l2_voltage is not None else None,
                "l3": _as_float(l3_voltage) if l3_voltage is not None else None,
            },
            "current_a": {
                "l1": _as_float(l1_current) if l1_current is not None else None,
                "l2": _as_float(l2_current) if l2_current is not None else None,
                "l3": _as_float(l3_current) if l3_current is not None else None,
            },
            "frequency_hz": {
                "l1": _as_float(l1_frequency) if l1_frequency is not None else None,
                "l2": _as_float(l2_frequency) if l2_frequency is not None else None,
                "l3": _as_float(l3_frequency) if l3_frequency is not None else None,
            },
            "power_factor": _as_float(inv_power_factor) if inv_power_factor is not None else None,
            "temperature_c": {
                "air": _as_float(inv_temp_air) if inv_temp_air is not None else None,
                "module": _as_float(inv_temp_module) if inv_temp_module is not None else None,
                "radiator": _as_float(inv_temp_radiator) if inv_temp_radiator is not None else None,
            },
        },
        "meter": {
            "status": {
                "test_status": _as_int(_pick(data, "meter_test_status")) if _pick(data, "meter_test_status") is not None else None,
                "comm_status": _as_int(_pick(data, "meter_comm_status")) if _pick(data, "meter_comm_status") is not None else None,
                "type": _as_int(_pick(data, "meter_type")) if _pick(data, "meter_type") is not None else None,
                "sw_version": _as_int(_pick(data, "meter_sw_version")) if _pick(data, "meter_sw_version") is not None else None,
            },
            "active_power_w": {
                "l1": _as_int(meter_l1_active) if meter_l1_active is not None else None,
                "l2": _as_int(meter_l2_active) if meter_l2_active is not None else None,
                "l3": _as_int(meter_l3_active) if meter_l3_active is not None else None,
                "total": _as_int(_pick(data, "meter_active_power_total")),
            },
            "reactive_power_var": {
                "l1": _as_int(_pick(data, "meter_reactive_power1")) if _pick(data, "meter_reactive_power1") is not None else None,
                "l2": _as_int(_pick(data, "meter_reactive_power2")) if _pick(data, "meter_reactive_power2") is not None else None,
                "l3": _as_int(_pick(data, "meter_reactive_power3")) if _pick(data, "meter_reactive_power3") is not None else None,
                "total": _as_int(_pick(data, "meter_reactive_power_total")) if _pick(data, "meter_reactive_power_total") is not None else None,
            },
            "apparent_power_va": {
                "l1": _as_int(_pick(data, "meter_apparent_power1")) if _pick(data, "meter_apparent_power1") is not None else None,
                "l2": _as_int(_pick(data, "meter_apparent_power2")) if _pick(data, "meter_apparent_power2") is not None else None,
                "l3": _as_int(_pick(data, "meter_apparent_power3")) if _pick(data, "meter_apparent_power3") is not None else None,
                "total": _as_int(_pick(data, "meter_apparent_power_total")) if _pick(data, "meter_apparent_power_total") is not None else None,
            },
            "energy_kwh": {
                "export_total": _as_float(_pick(data, "meter_e_total_exp", "meter_total_export_energy", "e_total_exp")),
                # Per-phase export energy: meter_e_total_exp1/2/3 at 36092/36096/36100 (Energy8, Wh/1000).
                "export_l1": _as_float(_pick(data, "meter_e_total_exp1")),
                "export_l2": _as_float(_pick(data, "meter_e_total_exp2")),
                "export_l3": _as_float(_pick(data, "meter_e_total_exp3")),
                "import_total": _as_float(_pick(data, "meter_e_total_imp", "meter_total_import_energy", "e_total_imp")),
                # Per-phase import energy: meter_e_total_imp1/2/3 at 36108/36112/36116 (Energy8, Wh/1000).
                "import_l1": _as_float(_pick(data, "meter_e_total_imp1")),
                "import_l2": _as_float(_pick(data, "meter_e_total_imp2")),
                "import_l3": _as_float(_pick(data, "meter_e_total_imp3")),
            },
            "power_factor": {
                "l1": _as_float(meter_pf_l1) if meter_pf_l1 is not None else None,
                "l2": _as_float(meter_pf_l2) if meter_pf_l2 is not None else None,
                "l3": _as_float(meter_pf_l3) if meter_pf_l3 is not None else None,
                "total": _as_float(meter_pf_total) if meter_pf_total is not None else None,
            },
            "voltage_v": {
                "l1": _as_float(meter_v1) if meter_v1 is not None else None,
                "l2": _as_float(meter_v2) if meter_v2 is not None else None,
                "l3": _as_float(meter_v3) if meter_v3 is not None else None,
            },
            "current_a": {
                "l1": _as_float(meter_i1) if meter_i1 is not None else None,
                "l2": _as_float(meter_i2) if meter_i2 is not None else None,
                "l3": _as_float(meter_i3) if meter_i3 is not None else None,
            },
            "frequency_hz": _as_float(meter_freq) if meter_freq is not None else None,
        },
        # Not exposed through the high-level SDK sensor API.
        "unknown_registers": {
            "39005": None,
            "47906": None,
            "47924": None,
        },
    }


async def poll_once(host: str, port: int, unit_id: int, timeout: float, family: str) -> dict[str, object]:
    inverter = await goodwe.connect(
        host,
        port=port,
        family=family,
        comm_addr=unit_id,
        timeout=timeout,
        retries=1,
        do_discover=False,
    )
    inverter.set_keep_alive(True)
    try:
        runtime_data = await inverter.read_runtime_data()
        model_name = str(getattr(inverter, "model_name", "") or "")
        external_model_name = str(getattr(inverter, "external_model_name", "") or "")
        if not external_model_name:
            external_model_name = await _read_external_model_name(inverter)

        try:
            runtime_data["power_factor"] = await inverter.read_setting("power_factor")
        except Exception:
            runtime_data["power_factor"] = runtime_data.get("power_factor")

        selected = {
            key: runtime_data.get(key)
            for key in (
                "timestamp",
                # PV
                "vpv1",
                "ipv1",
                "ppv1",
                "vpv2",
                "ipv2",
                "ppv2",
                "ppv",
                # Battery
                "vbattery1",
                "ibattery1",
                "pbattery1",
                # Meter active power
                "pgrid",
                "pgrid1",
                "pgrid2",
                "pgrid3",
                "active_power",
                "meter_active_power1",
                "meter_active_power2",
                "meter_active_power3",
                "meter_active_power_total",
                # Meter reactive power (SDK keys from et.py: Reactive/Reactive4 sensors)
                "reactive_power",
                "reactive_power_total",
                "reactive_power1",
                "reactive_power2",
                "reactive_power3",
                "meter_reactive_power1",
                "meter_reactive_power2",
                "meter_reactive_power3",
                "meter_reactive_power_total",
                # Meter apparent power (SDK keys from et.py: Apparent/Apparent4 sensors)
                "apparent_power",
                "apparent_power1",
                "apparent_power2",
                "apparent_power3",
                "meter_apparent_power1",
                "meter_apparent_power2",
                "meter_apparent_power3",
                "meter_apparent_power_total",
                # Inverter PF and temperatures
                "power_factor",
                "temperature_air",
                "temperature_module",
                "temperature",
                # Meter voltage
                "vgrid",
                "vgrid1",
                "vgrid2",
                "vgrid3",
                "fgrid",
                "fgrid2",
                "fgrid3",
                "vac1",
                "vac2",
                "vac3",
                # Meter diagnostic/status and aliases
                "meter_test_status",
                "meter_comm_status",
                "meter_type",
                "meter_sw_version",
                "meter_power_factor1",
                "meter_power_factor2",
                "meter_power_factor3",
                "meter_power_factor",
                "meter_freq",
                "meter_voltage1",
                "meter_voltage2",
                "meter_voltage3",
                "meter_current1",
                "meter_current2",
                "meter_current3",
                # Meter current
                "igrid",
                "igrid1",
                "igrid2",
                "igrid3",
                "iac1",
                "iac2",
                "iac3",
                # Meter energy totals (Energy8 at 36104/36120 overwrite f32 at 36015/36017 in SDK dict)
                "meter_e_total_exp",
                "meter_e_total_imp",
                # Meter energy per-phase export (Energy8 at 36092/36096/36100)
                "meter_e_total_exp1",
                "meter_e_total_exp2",
                "meter_e_total_exp3",
                # Meter energy per-phase import (Energy8 at 36108/36112/36116)
                "meter_e_total_imp1",
                "meter_e_total_imp2",
                "meter_e_total_imp3",
            )
            if key in runtime_data
        }

        return {
            "target": {"host": host, "port": port, "unit_id": unit_id, "family": family},
            "source": "goodwe-sdk",
            "sdk_sensor_count": len(runtime_data),
            "sdk_selected_values": selected,
            "decoded_key_values": _decode_from_sdk(runtime_data, model_name, external_model_name),
        }
    finally:
        # Explicitly close the socket after finishing all queries in this poll.
        await inverter._protocol.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read key GoodWe ET-style values from an emulator using the third-party goodwe SDK.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Inverter host")
    parser.add_argument("--port", type=int, default=8898, help="Socket-framed Modbus/TCP port")
    parser.add_argument("--unit-id", type=int, default=247, help="Modbus unit ID (comm address)")
    parser.add_argument("--family", default="ET", help="Inverter family for goodwe SDK (for example ET)")
    parser.add_argument("--timeout", type=float, default=2.0, help="TCP read timeout in seconds")
    args = parser.parse_args()

    result = asyncio.run(poll_once(args.host, args.port, args.unit_id, args.timeout, args.family))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
