from __future__ import annotations

import argparse
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig, ConfigError, load_config
from app.datasources.em540_client import Em540BridgeClient
from app.datasources.fronius_client import FroniusClient
from app.datasources.victron_client import VictronClient
from app.goodwe.register_map import build_register_map
from app.goodwe.server import GoodweModbusServer
from app.models import Snapshot
from app.version import __version__

logger = logging.getLogger(__name__)


@dataclass
class _SourcePollResult:
    name: str
    success: bool
    data: dict[str, float | int]


class EmulatorRuntime:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._snapshot = Snapshot()
        self._server = GoodweModbusServer(
            bind_host=self._cfg.goodwe_emulator.bind_host,
            rtu_port=self._cfg.goodwe_emulator.rtu_port,
            socket_port=self._cfg.goodwe_emulator.socket_port,
            comm_addr=self._cfg.goodwe_emulator.comm_addr,
            data_timeout=self._cfg.goodwe_emulator.data_timeout,
        )
        self._em540 = Em540BridgeClient(self._cfg.em540_bridge)
        self._fronius = FroniusClient(self._cfg.fronius)
        self._victron = VictronClient(self._cfg.victron)
        self._poll_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="upstream-poll")

    def run(self) -> None:
        updater = threading.Thread(target=self._update_loop, daemon=True)
        updater.start()
        self._server.serve_forever()

    def _update_loop(self) -> None:
        interval = max(0.2, self._cfg.goodwe_emulator.update_interval)
        while True:
            self._refresh_once()
            time.sleep(interval)

    def _refresh_once(self) -> bool:
        poll_specs = (
            ("em540", self._cfg.em540_bridge.enabled, self._em540.read, self._is_valid_em540),
            ("fronius", self._cfg.fronius.enabled, self._fronius.read, self._is_valid_fronius),
            ("victron", self._cfg.victron.enabled, self._victron.read, self._is_valid_victron),
        )

        futures = [
            self._poll_executor.submit(self._poll_source, name, enabled, reader, validator)
            for name, enabled, reader, validator in poll_specs
        ]
        results = tuple(f.result() for f in futures)

        failed = [result.name for result in results if not result.success]
        if failed:
            logger.warning("Holding downstream circuit open; upstream sources not ready: %s", ", ".join(failed))
            self._server.mark_upstream_failed()
            return False

        for result in results:
            self._merge(result.data)

        regs = build_register_map(self._snapshot, self._cfg.goodwe_emulator)
        self._server.update_holding_registers(regs)
        self._server.mark_data_received()
        return True

    def _poll_source(
        self,
        name: str,
        enabled: bool,
        reader: Callable[[], dict[str, float | int]],
        validator: Callable[[dict[str, float | int]], bool],
    ) -> _SourcePollResult:
        if not enabled:
            return _SourcePollResult(name=name, success=True, data={})

        try:
            data = reader()
        except Exception:
            logger.exception("Unhandled %s reader failure", name)
            return _SourcePollResult(name=name, success=False, data={})

        if name == "victron":
            data = self._transform_victron_battery_data(data)

        if not validator(data):
            logger.warning("Rejecting %s update; payload missing required valid fields", name)
            return _SourcePollResult(name=name, success=False, data={})

        return _SourcePollResult(name=name, success=True, data=data)

    def _transform_victron_battery_data(self, data: dict[str, float | int]) -> dict[str, float | int]:
        if not data:
            return data

        out: dict[str, float | int] = dict(data)
        vcfg = self._cfg.victron

        voltage_fields = (
            "battery_voltage_v",
            "battery_starter_voltage_v",
            "battery_midpoint_voltage_v",
            "battery_midpoint_deviation_v",
            "battery_max_charge_voltage_v",
            "battery_min_discharge_voltage_v",
        )
        current_fields = (
            "battery_current_a",
            "battery_max_charge_current_a",
            "battery_max_discharge_current_a",
        )
        scale = float(vcfg.battery_scale)

        for key in voltage_fields:
            if key in out:
                scaled = float(out[key]) * scale
                out[key] = max(float(vcfg.battery_voltage_min_v), min(float(vcfg.battery_voltage_max_v), scaled))

        for key in current_fields:
            if key in out:
                out[key] = float(out[key]) / scale

        return out

    @staticmethod
    def _is_valid_em540(data: dict[str, float | int]) -> bool:
        required = ("meter_voltage_l1_v", "meter_voltage_l2_v", "meter_voltage_l3_v", "meter_frequency_hz")
        return all(key in data for key in required) and all(float(data[key]) > 0 for key in required[:3])

    @staticmethod
    def _is_valid_fronius(data: dict[str, float | int]) -> bool:
        return "pv_power_w" in data

    @staticmethod
    def _is_valid_victron(data: dict[str, float | int]) -> bool:
        return "battery_voltage_v" in data and float(data["battery_voltage_v"]) > 0 and "battery_soc_pct" in data

    def _merge(self, update: dict[str, float | int]) -> None:
        for key, value in update.items():
            if hasattr(self._snapshot, key):
                setattr(self._snapshot, key, value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GoodWe ET inverter emulator")
    parser.add_argument("--config", default="config.yaml", help="Path to emulator config yaml")
    return parser.parse_args()


def run() -> None:
    args = _parse_args()
    if not Path(args.config).exists() and Path("config-default.yaml").exists():
        logger.warning("%s does not exist; using config-default.yaml", args.config)
        args.config = "config-default.yaml"

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    logging.basicConfig(
        level=getattr(logging, cfg.root.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Allow per-service log levels for Modbus clients/server while keeping a root default.
    logging.getLogger("app.datasources.em540_client").setLevel(cfg.em540_bridge.log_level)
    logging.getLogger("app.datasources.fronius_client").setLevel(cfg.fronius.log_level)
    logging.getLogger("app.datasources.victron_client").setLevel(cfg.victron.log_level)
    logging.getLogger("app.goodwe.server").setLevel(cfg.goodwe_emulator.log_level)

    logger.info("Starting GoodWe ET emulator version %s", __version__)

    runtime = EmulatorRuntime(cfg)
    runtime.run()
