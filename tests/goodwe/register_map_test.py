from app.config import GoodweEmulatorConfig
from app.goodwe.register_map import build_register_map
from app.models import Snapshot


def test_register_map_contains_core_blocks():
    cfg = GoodweEmulatorConfig()
    snap = Snapshot(meter_power_w=1200, pv_power_w=3000, battery_soc_pct=64, battery_voltage_v=52.4)
    regs = build_register_map(snap, cfg)

    assert regs[35000] == 1
    assert regs[35001] == cfg.rated_power
    assert 35103 in regs
    assert 36025 in regs
    assert regs[37007] == 64
    assert regs[47510] == 0


def test_register_map_contains_expanded_meter_fields():
    cfg = GoodweEmulatorConfig()
    snap = Snapshot(
        meter_power_w=900,
        inverter_active_power_w=450,
        inverter_reactive_power_var=-120,
        inverter_apparent_power_va=980,
        inverter_voltage_l1_v=234.5,
        inverter_voltage_l2_v=235.1,
        inverter_voltage_l3_v=236.2,
        inverter_current_l1_a=1.1,
        inverter_current_l2_a=1.2,
        inverter_current_l3_a=1.3,
        inverter_frequency_hz=49.97,
        inverter_power_l1_w=140,
        inverter_power_l2_w=150,
        inverter_power_l3_w=160,
        inverter_reactive_power_l1_var=-40,
        inverter_reactive_power_l2_var=-45,
        inverter_reactive_power_l3_var=-50,
        inverter_apparent_power_l1_va=320,
        inverter_apparent_power_l2_va=330,
        inverter_apparent_power_l3_va=340,
        inverter_power_factor=0.95,
        inverter_temperature_air_c=28.4,
        inverter_temperature_module_c=35.1,
        inverter_temperature_radiator_c=42.7,
        meter_power_l1_w=300,
        meter_power_l2_w=300,
        meter_power_l3_w=300,
        meter_reactive_power_l1_w=40,
        meter_reactive_power_l2_w=45,
        meter_reactive_power_l3_w=50,
        meter_reactive_power_total_w=135,
        meter_apparent_power_l1_w=320,
        meter_apparent_power_l2_w=330,
        meter_apparent_power_l3_w=340,
        meter_apparent_power_total_w=990,
        meter_power_factor_l1=0.97,
        meter_power_factor_l2=0.96,
        meter_power_factor_l3=0.95,
        meter_power_factor_total=0.96,
        meter_frequency_hz=49.98,
        meter_voltage_l1_v=229.4,
        meter_voltage_l2_v=230.1,
        meter_voltage_l3_v=231.0,
        meter_current_l1_a=1.3,
        meter_current_l2_a=1.4,
        meter_current_l3_a=1.5,
        meter_e_total_exp_kwh=12.34,
        meter_e_total_imp_kwh=56.78,
        meter_e_total_imp_l1_kwh=18.0,
        meter_e_total_imp_l2_kwh=19.0,
        meter_e_total_imp_l3_kwh=19.78,
    )
    regs = build_register_map(snap, cfg)

    assert regs[36005] == 300
    assert regs[36008] == 900
    assert regs[36009] == 135
    assert regs[36010] == 970
    assert regs[36014] == 4998
    assert regs[35140] == 450
    assert regs[35142] == 0xFF88
    assert regs[35144] == 980
    assert regs[35121] == 2345
    assert regs[35122] == 11
    assert regs[35123] == 4997
    assert regs[35124] == 0
    assert regs[35125] == 140
    assert regs[35126] == 2351
    assert regs[35127] == 12
    assert regs[35128] == 4997
    assert regs[35129] == 0
    assert regs[35130] == 150
    assert regs[35131] == 2362
    assert regs[35132] == 13
    assert regs[35133] == 4997
    assert regs[35134] == 0
    assert regs[35135] == 160
    assert regs[35137] == 0
    assert regs[35138] == 450
    assert regs[35353] == 0xFFFF
    assert regs[35354] == 0xFFD8
    assert regs[35355] == 0xFFFF
    assert regs[35356] == 0xFFD3
    assert regs[35357] == 0xFFFF
    assert regs[35358] == 0xFFCE
    assert regs[35359] == 0
    assert regs[35360] == 320
    assert regs[35361] == 0
    assert regs[35362] == 330
    assert regs[35363] == 0
    assert regs[35364] == 340
    assert regs[35174] == 284
    assert regs[35175] == 351
    assert regs[35176] == 427
    assert regs[45482] == 95
    assert regs[36025] == 0
    assert regs[36026] == 900
    assert regs[36027] == 0
    assert regs[36028] == 40
    assert regs[36041] == 0
    assert regs[36042] == 990
    assert regs[36052] == 2294
    assert regs[36055] == 13
    assert regs[36120] == 0


def test_register_map_rtc_packed_format():
    cfg = GoodweEmulatorConfig()
    regs = build_register_map(Snapshot(), cfg)

    year_month = regs[35100]
    day_hour = regs[35101]
    minute_second = regs[35102]

    year = (year_month >> 8) & 0xFF
    month = year_month & 0xFF
    day = (day_hour >> 8) & 0xFF
    hour = day_hour & 0xFF
    minute = (minute_second >> 8) & 0xFF
    second = minute_second & 0xFF

    assert 0 <= year <= 99
    assert 1 <= month <= 12
    assert 1 <= day <= 31
    assert 0 <= hour <= 23
    assert 0 <= minute <= 59
    assert 0 <= second <= 59


def test_runtime_data_populates_full_pv_channels():
    cfg = GoodweEmulatorConfig()
    snap = Snapshot(
        pv_power_w=3000,
        pv1_voltage_v=612.3,
        pv1_current_a=1.8,
        pv1_power_w=1102,
        pv2_voltage_v=612.1,
        pv2_current_a=1.7,
        pv2_power_w=1034,
        pv3_voltage_v=610.0,
        pv3_current_a=1.2,
        pv3_power_w=732,
        pv4_voltage_v=0.0,
        pv4_current_a=0.0,
        pv4_power_w=0,
    )
    regs = build_register_map(snap, cfg)

    assert regs[35103] == 6123
    assert regs[35104] == 18
    assert regs[35105] == 0
    assert regs[35106] == 1102

    assert regs[35107] == 6121
    assert regs[35108] == 17
    assert regs[35109] == 0
    assert regs[35110] == 1034

    assert regs[35111] == 6100
    assert regs[35112] == 12
    assert regs[35113] == 0
    assert regs[35114] == 732

    assert regs[35115] == 0
    assert regs[35116] == 0
    assert regs[35117] == 0
    assert regs[35118] == 0

    # 35137/35138 total inverter power should use summed PV channels.
    assert regs[35137] == 0
    assert regs[35138] == 2868


def test_battery_current_registers_use_snapshot_current_not_derived_power_ratio():
    cfg = GoodweEmulatorConfig()
    snap = Snapshot(
        battery_voltage_v=520.0,
        battery_power_w=5200,
        battery_current_a=12.3,
    )

    regs = build_register_map(snap, cfg)

    assert regs[35180] == 5200
    assert regs[35181] == 123
    assert regs[35182] == 0
    assert regs[35183] == 5200
    assert regs[37007] == 50  # SOC = snapshot default (50 %)
    assert regs[47906] == 5200


def test_external_model_name_written_to_register_35060():
    from app.goodwe.register_codec import get_ascii

    cfg = GoodweEmulatorConfig(external_model_name="EM540+Fronius+Victron")
    snap = Snapshot()
    regs = build_register_map(snap, cfg)

    # Verify external model name is written to 16 registers starting at 35060
    assert 35060 in regs
    assert 35075 in regs

    # Decode the ASCII string from registers
    decoded = get_ascii(regs, 35060, 16)
    assert decoded == "EM540+Fronius+Victron"


def test_blank_external_model_name_keeps_register_35060_block_zeroed():
    cfg = GoodweEmulatorConfig(external_model_name="")
    snap = Snapshot()
    regs = build_register_map(snap, cfg)

    # Prior behavior: keep these registers unwritten so reads return implicit zeros.
    for address in range(35060, 35076):
        assert regs.get(address, 0) == 0
