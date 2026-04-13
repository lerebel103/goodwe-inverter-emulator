from __future__ import annotations

from datetime import UTC, datetime

from app.config import GoodweEmulatorConfig
from app.goodwe.register_codec import put_ascii, put_f32, put_i16, put_i32, put_u16, put_u32, put_u64
from app.models import Snapshot


def build_register_map(snapshot: Snapshot, cfg: GoodweEmulatorConfig) -> dict[int, int]:
    regs: dict[int, int] = {}
    _device_info(regs, cfg)
    _runtime_data(regs, snapshot)
    _meter_data(regs, snapshot)
    _battery_data(regs, snapshot)
    _settings(regs, snapshot, cfg)
    return regs


def _device_info(regs: dict[int, int], cfg: GoodweEmulatorConfig) -> None:
    put_u16(regs, 35000, 1)
    put_u16(regs, 35001, cfg.rated_power)
    put_u16(regs, 35002, 1)
    put_ascii(regs, 35003, cfg.serial_number, 8)
    put_ascii(regs, 35011, cfg.model_name, 5)
    put_u16(regs, 35016, 100)
    put_u16(regs, 35017, 100)
    put_u16(regs, 35018, 1)
    put_u16(regs, 35019, 22)
    put_u16(regs, 35020, 1)
    put_ascii(regs, 35021, "EMUFW1", 6)


def _runtime_data(regs: dict[int, int], snapshot: Snapshot) -> None:
    now = datetime.now(UTC)
    # 35100..35102 are packed as high/low byte pairs per spec.
    put_u16(regs, 35100, ((now.year % 100) << 8) | now.month)
    put_u16(regs, 35101, (now.day << 8) | now.hour)
    put_u16(regs, 35102, (now.minute << 8) | now.second)

    put_u16(regs, 35103, int(max(0.0, snapshot.pv1_voltage_v) * 10.0))
    put_u16(regs, 35104, int(max(0.0, snapshot.pv1_current_a) * 10.0))
    put_u32(regs, 35105, max(0, int(snapshot.pv1_power_w)))
    put_u16(regs, 35107, int(max(0.0, snapshot.pv2_voltage_v) * 10.0))
    put_u16(regs, 35108, int(max(0.0, snapshot.pv2_current_a) * 10.0))
    put_u32(regs, 35109, max(0, int(snapshot.pv2_power_w)))
    put_u16(regs, 35111, int(max(0.0, snapshot.pv3_voltage_v) * 10.0))
    put_u16(regs, 35112, int(max(0.0, snapshot.pv3_current_a) * 10.0))
    put_u32(regs, 35113, max(0, int(snapshot.pv3_power_w)))
    put_u16(regs, 35115, int(max(0.0, snapshot.pv4_voltage_v) * 10.0))
    put_u16(regs, 35116, int(max(0.0, snapshot.pv4_current_a) * 10.0))
    put_u32(regs, 35117, max(0, int(snapshot.pv4_power_w)))

    put_u16(regs, 35121, int(max(0.0, snapshot.inverter_voltage_l1_v) * 10))
    put_u16(regs, 35122, int(max(0.0, snapshot.inverter_current_l1_a) * 10.0))
    put_u16(regs, 35123, int(max(0.0, snapshot.inverter_frequency_hz) * 100.0))
    put_i32(regs, 35124, int(snapshot.inverter_power_l1_w))
    put_u16(regs, 35126, int(max(0.0, snapshot.inverter_voltage_l2_v) * 10))
    put_u16(regs, 35127, int(max(0.0, snapshot.inverter_current_l2_a) * 10.0))
    put_u16(regs, 35128, int(max(0.0, snapshot.inverter_frequency_hz) * 100.0))
    put_i32(regs, 35129, int(snapshot.inverter_power_l2_w))
    put_u16(regs, 35131, int(max(0.0, snapshot.inverter_voltage_l3_v) * 10))
    put_u16(regs, 35132, int(max(0.0, snapshot.inverter_current_l3_a) * 10.0))
    put_u16(regs, 35133, int(max(0.0, snapshot.inverter_frequency_hz) * 100.0))
    put_i32(regs, 35134, int(snapshot.inverter_power_l3_w))

    put_u16(regs, 35136, 1)
    total_pv = int(snapshot.pv1_power_w + snapshot.pv2_power_w + snapshot.pv3_power_w + snapshot.pv4_power_w)
    if total_pv <= 0:
        total_pv = int(snapshot.pv_power_w)
    total_inverter_power = (
        int(snapshot.inverter_active_power_w) if int(snapshot.inverter_active_power_w) != 0 else total_pv
    )
    put_i32(regs, 35137, total_inverter_power)

    put_i16(regs, 35140, int(snapshot.inverter_active_power_w))
    put_i16(regs, 35142, int(snapshot.inverter_reactive_power_var))
    put_u16(regs, 35144, max(0, int(snapshot.inverter_apparent_power_va)))
    put_i16(regs, 35174, int(snapshot.inverter_temperature_air_c * 10.0))
    put_i16(regs, 35175, int(snapshot.inverter_temperature_module_c * 10.0))
    put_i16(regs, 35176, int(snapshot.inverter_temperature_radiator_c * 10.0))
    # Extended inverter per-phase reactive/apparent channels used by the SDK
    # (reactive_power1..3, apparent_power1..3).
    put_i32(regs, 35353, int(snapshot.inverter_reactive_power_l1_var))
    put_i32(regs, 35355, int(snapshot.inverter_reactive_power_l2_var))
    put_i32(regs, 35357, int(snapshot.inverter_reactive_power_l3_var))
    put_i32(regs, 35359, int(snapshot.inverter_apparent_power_l1_va))
    put_i32(regs, 35361, int(snapshot.inverter_apparent_power_l2_va))
    put_i32(regs, 35363, int(snapshot.inverter_apparent_power_l3_va))
    put_i32(regs, 35182, int(snapshot.battery_power_w))
    put_u16(regs, 35180, int(snapshot.battery_voltage_v * 10))
    put_i16(regs, 35181, int(snapshot.battery_current_a * 10))
    put_u16(regs, 35184, 3)
    put_u16(regs, 35187, 1)
    put_u16(regs, 35188, 0)


def _meter_data(regs: dict[int, int], snapshot: Snapshot) -> None:
    put_u16(regs, 36000, 1)
    put_u16(regs, 36001, 100)
    put_u16(regs, 36002, 1)
    put_u16(regs, 36003, 1)
    put_u16(regs, 36004, 1)
    put_i16(regs, 36005, int(snapshot.meter_power_l1_w))
    put_i16(regs, 36006, int(snapshot.meter_power_l2_w))
    put_i16(regs, 36007, int(snapshot.meter_power_l3_w))
    put_i16(regs, 36008, int(snapshot.meter_power_w))
    put_i16(regs, 36009, int(snapshot.meter_reactive_power_total_w))
    put_i16(regs, 36010, int(snapshot.meter_power_factor_l1 * 1000.0))
    put_i16(regs, 36011, int(snapshot.meter_power_factor_l2 * 1000.0))
    put_i16(regs, 36012, int(snapshot.meter_power_factor_l3 * 1000.0))
    put_i16(regs, 36013, int(snapshot.meter_power_factor_total * 1000.0))
    put_u16(regs, 36014, int(snapshot.meter_frequency_hz * 100.0))
    put_f32(regs, 36015, snapshot.meter_e_total_exp_kwh)
    put_f32(regs, 36017, snapshot.meter_e_total_imp_kwh)

    put_i32(regs, 36019, int(snapshot.meter_power_l1_w))
    put_i32(regs, 36021, int(snapshot.meter_power_l2_w))
    put_i32(regs, 36023, int(snapshot.meter_power_l3_w))
    put_i32(regs, 36025, int(snapshot.meter_power_w))
    put_i32(regs, 36027, int(snapshot.meter_reactive_power_l1_w))
    put_i32(regs, 36029, int(snapshot.meter_reactive_power_l2_w))
    put_i32(regs, 36031, int(snapshot.meter_reactive_power_l3_w))
    put_i32(regs, 36033, int(snapshot.meter_reactive_power_total_w))
    put_i32(regs, 36035, int(snapshot.meter_apparent_power_l1_w))
    put_i32(regs, 36037, int(snapshot.meter_apparent_power_l2_w))
    put_i32(regs, 36039, int(snapshot.meter_apparent_power_l3_w))
    put_i32(regs, 36041, int(snapshot.meter_apparent_power_total_w))

    put_u16(regs, 36052, int(snapshot.meter_voltage_l1_v * 10))
    put_u16(regs, 36053, int(snapshot.meter_voltage_l2_v * 10))
    put_u16(regs, 36054, int(snapshot.meter_voltage_l3_v * 10))
    put_u16(regs, 36055, int(snapshot.meter_current_l1_a * 10.0))
    put_u16(regs, 36056, int(snapshot.meter_current_l2_a * 10.0))
    put_u16(regs, 36057, int(snapshot.meter_current_l3_a * 10.0))
    put_u16(regs, 36043, 2)
    put_u16(regs, 36044, 1)

    # Extended cumulative energies used by newer ET clients.
    e_exp_wh = max(0, int(snapshot.meter_e_total_exp_kwh * 1000.0))
    e_imp_wh = max(0, int(snapshot.meter_e_total_imp_kwh * 1000.0))
    e_imp_l1_wh = max(0, int(snapshot.meter_e_total_imp_l1_kwh * 1000.0))
    e_imp_l2_wh = max(0, int(snapshot.meter_e_total_imp_l2_kwh * 1000.0))
    e_imp_l3_wh = max(0, int(snapshot.meter_e_total_imp_l3_kwh * 1000.0))
    put_u64(regs, 36092, 0)
    put_u64(regs, 36096, 0)
    put_u64(regs, 36100, 0)
    put_u64(regs, 36104, e_exp_wh)
    put_u64(regs, 36108, e_imp_l1_wh)
    put_u64(regs, 36112, e_imp_l2_wh)
    put_u64(regs, 36116, e_imp_l3_wh)
    put_u64(regs, 36120, e_imp_wh)


def _battery_data(regs: dict[int, int], snapshot: Snapshot) -> None:
    """Map battery data to GoodWe ET battery registers."""
    # Battery status and control
    put_u16(regs, 37000, 1)  # Battery connect status: 1=connected
    put_u16(regs, 37003, 250)  # Battery capacity

    # Battery voltage and current
    put_u16(regs, 37006, int(snapshot.battery_voltage_v * 10))  # Battery voltage
    put_i16(regs, 37007, int(snapshot.battery_current_a * 10))  # Battery current

    # Battery power
    put_i32(regs, 37008, int(snapshot.battery_power_w))  # Battery power

    # Battery SOC and state
    put_u16(regs, 37010, int(snapshot.battery_soc_pct))  # SOC
    put_u16(regs, 37011, snapshot.battery_state)  # Battery state (0=idle, 1=charging, 2=discharging)

    # Battery temperature (if available)
    put_i16(regs, 37013, int(snapshot.battery_temperature_c * 10))  # Battery temperature

    # Battery health
    put_u16(regs, 37015, int(snapshot.battery_state_of_health_pct))  # State of health

    # Battery capacity and consumed energy
    put_u16(regs, 37016, int(snapshot.battery_capacity_ah))  # Capacity
    put_i32(regs, 37017, int(snapshot.battery_consumed_ah * 10))  # Consumed Ah (scale 10)

    # Battery voltage limits
    put_u16(regs, 37019, int(snapshot.battery_max_charge_voltage_v * 10))  # Max charge voltage
    put_u16(regs, 37020, int(snapshot.battery_min_discharge_voltage_v * 10))  # Min discharge voltage

    # Battery current limits
    put_i16(regs, 37021, int(snapshot.battery_max_charge_current_a * 10))  # Max charge current
    put_i16(regs, 37022, int(snapshot.battery_max_discharge_current_a * 10))  # Max discharge current

    # Battery alarms and errors
    put_u16(regs, 37023, snapshot.battery_alarm)  # Alarm status
    put_u16(regs, 37024, snapshot.battery_error)  # Error code


def _settings(regs: dict[int, int], snapshot: Snapshot, cfg: GoodweEmulatorConfig) -> None:
    put_u16(regs, 45127, cfg.comm_addr)
    put_u16(regs, 45356, 100 - int(snapshot.battery_soc_pct))
    put_i16(regs, 45482, int(snapshot.inverter_power_factor * 100.0))
    put_u16(regs, 47000, 0)
    put_u16(regs, 47509, 1)
    put_u16(regs, 47510, int(snapshot.grid_export_limit_w))
    put_u16(regs, 47511, 0)
    put_u16(regs, 47512, int(snapshot.grid_export_limit_w))
