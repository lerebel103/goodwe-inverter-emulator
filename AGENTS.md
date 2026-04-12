# AGENTS.md

## Purpose

This project emulates a GoodWe ET-series hybrid inverter over Modbus/TCP.

It aggregates data from:
- Carlo Gavazzi EM540 bridge (meter data)
- Fronius Symo inverter (PV data)
- Victron GX device (battery data)

## Key Commands

- Test: `make test`
- Lint: `make lint`
- Format: `make format`
- Start stack: `make up`
- Stop stack: `make down`
- Logs: `make logs`

## Reliability Guardrails

- Reconnect, disconnect, and network-recovery behavior must be explicit and tested for every Modbus client and server path.
- Never propagate stale, partial, or invalid upstream data to downstream Modbus consumers.
- Keep the downstream circuit breaker as the primary safety boundary, and open it whenever upstream freshness or validity is uncertain.
