# GoodWe ET Inverter Emulator

[![GitHub](https://img.shields.io/badge/GitHub-lerebel103%2Fgoodwe--inverter--emulator-blue?logo=github)](https://github.com/lerebel103/goodwe-inverter-emulator)

GoodWe ET-series hybrid inverter emulator created to allow a GoodWe HCA G2 22kW EV charger to operate in environments where no physical GoodWe inverter is installed.

Although it was developed for this EV charger use case, it may also work with other GoodWe appliances that require inverter-style data over Modbus.

It aggregates data from:

- EM540 bridge (meter data over Modbus/TCP)
- Fronius Symo (PV data over Modbus/TCP)
- Victron GX (battery data over Modbus/TCP)

The EM540 in this integration refers to the Carlo Gavazzi EM540 energy meter, selected for high sampling rates and accuracy for grid telemetry.

Validation support in this repository also uses the open-source GoodWe Python SDK from `marcelblijleven/goodwe`: https://github.com/marcelblijleven/goodwe

This emulator was developed to work directly with the EM540 bridge from:

- https://github.com/lerebel103/carlo-gavazzi-em540-bridge

It expects EM540 meter telemetry from that bridge project and maps it into a GoodWe ET-compatible Modbus register image.

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
- `goodwe_emulator.comm_addr`: Modbus device ID expected by your downstream client (for example charger)
- `goodwe_emulator.socket_port`: TCP listening port for downstream clients

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

The following addresses were repeatedly requested by the HCA G2 during the latest capture (09:24:32..09:24:43):

| Address | Count | Observed TX payload (sample/range) | Notes |
|---|---:|---|---|
| 35060 | 16 | `[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]` | Zero-filled block in current emulator |
| 35011 | 5 | `[18263, 12592, 19245, 17748, 8224]` | Model name block |
| 35100 | 1 | `[6660]` | RTC packed year/month |
| 35137 | 2 | `[0, 5012] .. [0, 5016]` | Signed 32-bit total inverter/PV watts |
| 37007 | 1 | `[670] .. [667]` | Battery current (`0.1 A` scale) |
| 39005 | 1 | `[0]` | Observed zero |
| 35180 | 1 | `[536]` | Battery voltage (`0.1 V` scale) |
| 47906 | 1 | `[0]` | Observed zero |
| 35262 | 1 | `[0]` | Observed zero |
| 47924 | 1 | `[0]` | Observed zero |
| 36025 | 2 | `[0, 32] .. [0, 56]` | Signed 32-bit meter total active power |
| 36055 | 3 | `[22, 20, 34] .. [22, 20, 35]` | Meter currents L1/L2/L3 (`0.1 A`) |
| 35105 | 14 | `[0, 1179, 2784, 145, 0, 4047..4050, 0, 0, 0, 0, 0, 0, 0, 0]` | PV detail/runtime block |

### Register Decoding Notes for This Poll Set

- `35100`: packed as `(year % 100) << 8 | month`
- `35137..35138`: signed 32-bit watts (`i32`), total PV power
- `35180`: battery voltage in `0.1 V` units
- `36025..36026`: signed 32-bit watts (`i32`), total meter active power
- `36055..36057`: phase currents in `0.1 A` units
- `37007`: battery current in `0.1 A` units

### Example Values Seen in Validation Run

- `35137..35138`: `5012..5016 W` (signed 32-bit total inverter/PV)
- `35180`: `53.6 V`
- `37007`: `66.7..67.0 A`
- `36025..36026`: `32..56 W` (signed 32-bit)
- `36055..36057`: `2.2 A`, `2.0 A`, `3.4..3.5 A`

These values are consistent with the current mapping implemented in `app/goodwe/register_map.py` and with circuit-breaker behavior in `app/goodwe/server.py`.
