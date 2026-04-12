# GoodWe ET Inverter Emulator

GoodWe ET-series hybrid inverter emulator that aggregates data from:

- EM540 bridge (meter data over Modbus/TCP)
- Fronius Symo (PV data over Modbus/TCP)
- Victron GX (battery data over Modbus/TCP)

The project is Modbus-only for runtime integrations and emulation.

It serves a GoodWe-like Modbus/TCP endpoint so tools such as the Python `goodwe` ET client can connect and read expected ET register ranges.

Validation support in this repository also uses the open-source GoodWe Python SDK from `marcelblijleven/goodwe`: https://github.com/marcelblijleven/goodwe

## Functional Goals

- Emulate a GoodWe ET-series Modbus/TCP inverter interface so a GoodWe HCA G2 22kW EV charger can operate with full inverter-driven functionality even when no physical GoodWe inverter is present.
- Aggregate meter, PV, and battery telemetry from upstream systems (EM540 bridge, Fronius Symo, and Victron GX) into a single coherent ET-style register image.
- Serve the core ET register ranges and scaling conventions used by downstream clients, with stable decoding for power, voltage, current, RTC, and energy values.
- Protect downstream consumers from invalid or stale upstream data by using an explicit readiness gate plus a downstream circuit breaker that rejects reads until data is fresh.
- Provide a practical integration bridge for non-GoodWe sites that need charger compatibility and behavior close to a real GoodWe ET inverter.

## Quick Start

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

4. Or run with Docker:

```bash
make up
```

## Quality Gates

- Lint: `make lint`
- Format: `make format`
- Tests: `make test`

## Current Register Coverage

The emulator currently implements core ET ranges used by common clients:

- Device info: `35000-35032`
- Runtime block: `35100+`
- Meter block: `36000+`
- Battery block: `37000+`
- Key settings: `45127`, `45356`, `47509-47512`

This is intentionally extensible so you can complete strict one-to-one mapping from your official GoodWe ET PDF.

## GoodWe HCA G2 22kW Charger Validation

This emulator was tested against a GoodWe HCA G2 22kW EV charger that polls the inverter over Modbus/TCP using function code 3.

Credit: the standalone validation client in this repository is built on top of the open-source GoodWe Python SDK maintained at `marcelblijleven/goodwe`.

### Observed Startup Behavior (Fresh Restart)

- On restart, the downstream circuit breaker starts open until fresh upstream data is available.
- The downstream stale-data timeout is 10 seconds by default (`goodwe_emulator.data_timeout`) to provide headroom while still failing safe quickly.
- While open, the charger requests are rejected with Modbus exception responses (`fc=131` in logs, which is exception response for read-holding-registers).
- After upstream data arrives, the breaker closes and normal `fc=3` register responses resume.

### Observed Charger Register Poll Set

The following addresses were repeatedly requested by the HCA G2 during the capture:

- `35011` count `5` (model name block)
- `35060` count `16` (observed zero-filled in current emulator)
- `35100` count `1` (RTC packed year/month)
- `35105` count `14` (PV detail block)
- `35137` count `2` (total PV power)
- `35180` count `1` (battery voltage)
- `35262` count `1` (observed zero)
- `36025` count `2` (meter total active power, signed 32-bit)
- `36055` count `3` (meter currents L1/L2/L3)
- `37007` count `1` (battery current)
- `39005` count `1` (observed zero)
- `47906` count `1` (observed zero)
- `47924` count `1` (observed zero)

### Register Decoding Notes for This Poll Set

- `35100`: packed as `(year % 100) << 8 | month`
- `35137..35138`: signed 32-bit watts (`i32`), total PV power
- `35180`: battery voltage in `0.1 V` units
- `36025..36026`: signed 32-bit watts (`i32`), total meter active power
- `36055..36057`: phase currents in `0.1 A` units
- `37007`: battery current in `0.1 A` units

### Example Values Seen in Validation Run

- `35137`: `5979..5982 W` (total PV)
- `35180`: `54.3 V`
- `37007`: `58.0 A`
- `36025`: `105 W`
- `36055..36057`: `3.2 A`, `3.3 A`, `6.3 A`

These values are consistent with the current mapping implemented in `app/goodwe/register_map.py` and with circuit-breaker behavior in `app/goodwe/server.py`.
