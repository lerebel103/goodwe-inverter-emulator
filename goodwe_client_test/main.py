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


def _decode_from_sdk(data: dict[str, object], model_name: str | None) -> dict[str, object]:
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

    l1_current = _pick(data, "igrid1", "iac1", "igrid")
    l2_current = _pick(data, "igrid2", "iac2")
    l3_current = _pick(data, "igrid3", "iac3")

    l1_voltage = _pick(data, "vgrid1", "vgrid", "vac1")
    l2_voltage = _pick(data, "vgrid2", "vac2")
    l3_voltage = _pick(data, "vgrid3", "vac3")

    l1_power = _pick(data, "pgrid1", "meter_active_power1", "pgrid")
    l2_power = _pick(data, "pgrid2", "meter_active_power2")
    l3_power = _pick(data, "pgrid3", "meter_active_power3")

    return {
        "model_name": model_name or _pick(data, "model_name", default=""),
        "rtc": {
            "year_2digit": year_2digit,
            "month": month,
            "raw": rtc_raw,
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
        },
        "total_inverter_power_w": _as_int(_pick(data, "ppv", "ppv_total")),
        "battery_voltage_v": _as_float(_pick(data, "vbattery1", "battery_voltage")),
        "battery_voltage_2_v": _as_float(_pick(data, "vbattery2", default=0.0)),
        "battery_current_a": _as_float(_pick(data, "ibattery1", "battery_current")),
        "meter_power_total_w": _as_int(_pick(data, "meter_active_power_total", "active_power", "pgrid")),
        "meter_powers_w": {
            "l1": _as_int(l1_power) if l1_power is not None else None,
            "l2": _as_int(l2_power) if l2_power is not None else None,
            "l3": _as_int(l3_power) if l3_power is not None else None,
            "total": _as_int(_pick(data, "meter_active_power_total", "active_power", "pgrid")),
        },
        "meter_voltages_v": {
            "l1": _as_float(l1_voltage) if l1_voltage is not None else None,
            "l2": _as_float(l2_voltage) if l2_voltage is not None else None,
            "l3": _as_float(l3_voltage) if l3_voltage is not None else None,
        },
        "meter_currents_a": {
            "l1": _as_float(l1_current),
            "l2": _as_float(l2_current) if l2_current is not None else None,
            "l3": _as_float(l3_current) if l3_current is not None else None,
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
    runtime_data = await inverter.read_runtime_data()
    model_name = str(getattr(inverter, "model_name", "") or "")

    selected = {
        key: runtime_data.get(key)
        for key in (
            "timestamp",
            "vpv1",
            "ipv1",
            "ppv1",
            "vpv2",
            "ipv2",
            "ppv2",
            "ppv",
            "vbattery1",
            "ibattery1",
            "pbattery1",
            "pgrid",
            "pgrid1",
            "pgrid2",
            "pgrid3",
            "active_power",
            "vgrid",
            "vgrid1",
            "vgrid2",
            "vgrid3",
            "vac1",
            "vac2",
            "vac3",
            "igrid",
            "igrid1",
            "igrid2",
            "igrid3",
            "iac1",
            "iac2",
            "iac3",
            "meter_active_power1",
            "meter_active_power2",
            "meter_active_power3",
            "meter_active_power_total",
        )
        if key in runtime_data
    }

    return {
        "target": {"host": host, "port": port, "unit_id": unit_id, "family": family},
        "source": "goodwe-sdk",
        "sdk_sensor_count": len(runtime_data),
        "sdk_selected_values": selected,
        "decoded_key_values": _decode_from_sdk(runtime_data, model_name),
    }


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
