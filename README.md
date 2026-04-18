# GoodWe ET Inverter Emulator

[![GitHub](https://img.shields.io/badge/GitHub-lerebel103%2Fgoodwe--inverter--emulator-blue?logo=github)](https://github.com/lerebel103/goodwe-inverter-emulator)

GoodWe ET-series hybrid inverter emulator created to allow a GoodWe HCA G2 22kW EV charger to operate in environments where no physical GoodWe inverter is installed.

Although it was developed for this EV charger use case, it may also work with other GoodWe appliances that require inverter-style data over Modbus.

It aggregates data from:

- EM540 bridge from https://github.com/lerebel103/carlo-gavazzi-em540-bridge (meter data over Modbus/TCP; this emulator was developed to work directly with this bridge)
- Fronius Symo (PV data over Modbus/TCP)
- Victron GX (battery data over Modbus/TCP)

The EM540 in this integration refers to the Carlo Gavazzi EM540 energy meter, selected for high sampling rates and accuracy for grid telemetry.

Validation support in this repository also uses the open-source GoodWe Python SDK from `marcelblijleven/goodwe`: https://github.com/marcelblijleven/goodwe


## Features

- GoodWe ET-style Modbus/TCP register emulation for downstream clients (including HCA charger scenarios)
- Aggregation of meter (EM540 bridge), PV (Fronius), and battery (Victron) telemetry
- Safety-first freshness gate with downstream Modbus circuit breaker behavior
- Validation client built on the open-source GoodWe Python SDK

## Requirements

- Physical RS485-to-TCP converter (for example USR-TCP232-304) to allow the EV charger RS485/Modbus side to connect to this app over TCP
- Upstream EM540 bridge running and reachable over the configured host/port
- Victron GX device reachable on the network with Modbus/TCP enabled
- Fronius Snap Inverter reachable on the network with Modbus enabled
- Docker Engine + Docker Compose plugin
- Optional manual path only: Python 3.13+ with dependencies from `requirements*.txt`

## Install and Run with Docker Compose (Recommended)

This repository ships with a compose file that points to the pre-built image:

- `lerebel103/goodwe-et-inverter-emulator:latest`

Use `docker compose` directly to pull and run that image (without local rebuild).

1. Copy `config-default.yaml` to `config.yaml` and adjust hostnames/IPs.
2. Configure `config.yaml` for your environment:

- `em540_bridge.host` / `em540_bridge.port`: address of the EM540 bridge service
- `fronius.host` / `fronius.port`: Fronius endpoint
- `victron.host` / `victron.port`: Victron endpoint
- Victron battery systems are typically low-voltage (for example around 48-52V), while GoodWe ET battery telemetry expects a higher-voltage range, so `victron.battery_scale` is used to better emulate ET-style battery voltage/current behavior.
- `victron.battery_scale`: optional LV-to-HV battery scaling factor (voltage values are multiplied by this factor, current values are divided by this factor)
- `victron.battery_voltage_min_v`, `victron.battery_voltage_max_v`: clamp window applied after voltage scaling
- `goodwe_emulator.comm_addr`: Modbus device ID expected by your downstream client (for example charger)
- `goodwe_emulator.socket_port`: TCP listening port for downstream clients

Optional synthetic test profile (for lab validation without changing upstream devices):

- `fronius.synthetic_pv_enabled`: force PV telemetry to configured synthetic values
- `fronius.synthetic_pv_total_power_w`: total PV power (default `8200` W), split evenly over PV1/PV2
- `fronius.synthetic_pv1_voltage_v`, `fronius.synthetic_pv2_voltage_v`: PV string voltages used to derive current with `P = V x I`
- `em540_bridge.synthetic_grid_export_enabled`: force meter active power to synthetic grid export values
- `em540_bridge.synthetic_grid_total_power_w`: total grid active power (default `-4500` W export)
- `em540_bridge.synthetic_grid_frequency_hz`: injected grid frequency

When synthetic grid export is enabled, live EM540 voltages still pass through from the upstream meter, while active power sign remains the source of import/export direction and currents are reported as magnitudes.

3. Start with pre-built image:

```bash
docker compose pull
docker compose up -d
```

4. View logs:

```bash
docker compose logs -f goodwe-et-inverter-emulator
```

5. Stop the stack:

```bash
docker compose down
```

Notes:

- The compose file mounts `./config.yaml` into the container at `/etc/goodwe-emulator/config.yaml`.
- Port `8899` is published by default from the compose file.
- `make up` currently runs compose with `--build`; use the commands above when you want pre-built images only.

## Build and Run Manually (Optional, Non-Docker)

Use this path only if you do not want Docker.

Prerequisite: deploy and run the EM540 meter bridge service before starting this emulator, because meter telemetry is sourced from that upstream service.

This project was designed to work alongside the `carlo-gavazzi-em540-bridge` project. Ensure the bridge host/port are reachable from this emulator and configured in `config.yaml`.

1. Copy `config-default.yaml` to `config.yaml` and adjust hostnames/IPs.
2. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

3. Run locally:

```bash
python -m app --config config.yaml
```

4. (Optional) Run checks:

```bash
make lint
make test
```

## Quality Gates

- Lint: `make lint`
- Format: `make format`
- Tests: `make test`

To enable the repository's tracked pre-commit hook locally, run:

```bash
make install-hooks
```

The pre-commit hook runs `make lint`.

## Current Register Coverage

The emulator currently implements core ET ranges used by common clients:

- Device info: `35000-35032`
- Runtime block: `35100+`
- Meter block: `36000+`
- Battery block: `37000+`
- Key settings: `45127`, `45356`, `45482`, `47509-47512`

This is intentionally extensible so you can complete strict one-to-one mapping from your official GoodWe ET PDF.

## GoodWe HCA G2 22kW Charger Validation

This emulator was tested against a GoodWe HCA G2 22kW EV charger that polls the inverter over Modbus/TCP using function code 3.

Credit: the standalone validation client in this repository is built on top of the open-source GoodWe Python SDK maintained at `marcelblijleven/goodwe`.

### Observed Startup Behavior (Fresh Restart)

- On restart, the downstream circuit breaker starts open until fresh upstream data is available.
- The downstream stale-data timeout is 5 seconds by default (`goodwe_emulator.data_timeout`) to provide headroom while still failing safe quickly.
- While open, the charger requests are rejected with Modbus exception responses (`fc=131` in logs, which is exception response for read-holding-registers).
- After upstream data arrives, the breaker closes and normal `fc=3` register responses resume.

### Observed Charger Register Poll Set

For reference, the following addresses are requested by the HCA G2:

| Address | Count | Observed TX payload (sample/range) | Notes | Decoded example |
|---|---:|---|---|---|
| 35060 | 16 | `[18263, 12592, 19245, 17748, 8224, 8224, ...]` | External Model Name (string block) | `GW10K-ET` |
| 35100 | 1 | `[6660]` | RTC packed year/month | `0x1A04` => year `26`, month `4` |
| 35137 | 2 | `[0, 2652] .. [0, 2673]` | Signed 32-bit total inverter/PV watts | `2652..2673 W` |
| 37007 | 1 | `[64]` | Battery SOC (BMS Operation Data, `U16`, `1 %` scale) | `64 %` |
| 39005 | 1 | `[0]` | BMS2 SOC (secondary battery channel) | `0 %` |
| 35180 | 1 | `[5480]` | Battery voltage (`0.1 V` scale) | `548.0 V` |
| 47906 | 1 | `[5480]` | BMS battery voltage (`0.1 V` scale, RW BMS path) | `548.0 V` |
| 35262 | 1 | `[0]` | Battery2 voltage (`0.1 V`, secondary channel) | `0.0 V` |
| 47924 | 1 | `[0]` | BMS battery2 voltage (RW BMS path) | `0.0 V` |
| 36025 | 2 | `[65535, 64045] .. [65535, 64075]` | Signed 32-bit meter total active power | `-1491..-1461 W` |
| 36055 | 3 | `[33, 29, 20] .. [34, 29, 21]` | Meter currents L1/L2/L3 (`0.1 A`) | `3.3..3.4 A`, `2.8..2.9 A`, `2.0..2.1 A` |
| 35105 | 14 | `[0, 50, 3126..3129, 87..88, 0, 2731..2763, 0, 0, 0, 0, 0, 0, 0, 0]` | PV detail/runtime block | e.g. PV1 power `50 W`; PV2 `312.6..312.9 V`, `8.7..8.8 A`, `2731..2763 W` |

