from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Snapshot:
    meter_power_w: int = 0
    meter_power_l1_w: int = 0
    meter_power_l2_w: int = 0
    meter_power_l3_w: int = 0
    meter_reactive_power_l1_w: int = 0
    meter_reactive_power_l2_w: int = 0
    meter_reactive_power_l3_w: int = 0
    meter_reactive_power_total_w: int = 0
    meter_apparent_power_l1_w: int = 0
    meter_apparent_power_l2_w: int = 0
    meter_apparent_power_l3_w: int = 0
    meter_apparent_power_total_w: int = 0
    meter_power_factor_l1: float = 1.0
    meter_power_factor_l2: float = 1.0
    meter_power_factor_l3: float = 1.0
    meter_power_factor_total: float = 1.0
    meter_frequency_hz: float = 50.0
    meter_voltage_l1_v: float = 230.0
    meter_voltage_l2_v: float = 230.0
    meter_voltage_l3_v: float = 230.0
    meter_current_l1_a: float = 0.0
    meter_current_l2_a: float = 0.0
    meter_current_l3_a: float = 0.0
    meter_e_total_exp_kwh: float = 0.0
    meter_e_total_imp_kwh: float = 0.0
    meter_e_total_imp_l1_kwh: float = 0.0
    meter_e_total_imp_l2_kwh: float = 0.0
    meter_e_total_imp_l3_kwh: float = 0.0
    inverter_active_power_w: int = 0
    inverter_reactive_power_var: int = 0
    inverter_apparent_power_va: int = 0
    inverter_voltage_l1_v: float = 0.0
    inverter_voltage_l2_v: float = 0.0
    inverter_voltage_l3_v: float = 0.0
    inverter_current_l1_a: float = 0.0
    inverter_current_l2_a: float = 0.0
    inverter_current_l3_a: float = 0.0
    inverter_frequency_hz: float = 50.0
    inverter_power_l1_w: int = 0
    inverter_power_l2_w: int = 0
    inverter_power_l3_w: int = 0
    inverter_reactive_power_l1_var: int = 0
    inverter_reactive_power_l2_var: int = 0
    inverter_reactive_power_l3_var: int = 0
    inverter_apparent_power_l1_va: int = 0
    inverter_apparent_power_l2_va: int = 0
    inverter_apparent_power_l3_va: int = 0
    pv_power_w: int = 0
    pv1_voltage_v: float = 0.0
    pv1_current_a: float = 0.0
    pv1_power_w: int = 0
    pv2_voltage_v: float = 0.0
    pv2_current_a: float = 0.0
    pv2_power_w: int = 0
    pv3_voltage_v: float = 0.0
    pv3_current_a: float = 0.0
    pv3_power_w: int = 0
    pv4_voltage_v: float = 0.0
    pv4_current_a: float = 0.0
    pv4_power_w: int = 0
    battery_soc_pct: int = 50
    battery_voltage_v: float = 52.0
    battery_power_w: int = 0
    battery_current_a: float = 0.0
    battery_temperature_c: float = 25.0
    battery_state: int = 0  # 0=idle, 1=charging, 2=discharging
    battery_alarm: int = 0
    battery_error: int = 0
    battery_consumed_ah: float = 0.0
    battery_time_to_go_s: int = 0
    battery_state_of_health_pct: float = 100.0
    battery_capacity_ah: float = 100.0
    battery_max_charge_voltage_v: float = 58.0
    battery_min_discharge_voltage_v: float = 40.0
    battery_max_charge_current_a: float = 50.0
    battery_max_discharge_current_a: float = 50.0
    battery_starter_voltage_v: float = 13.6
    battery_midpoint_voltage_v: float = 26.0
    battery_midpoint_deviation_v: float = 0.0
    grid_export_limit_w: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
