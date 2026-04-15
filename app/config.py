from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass
class Em540BridgeConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 5001
    slave_id: int = 1
    timeout: float = 1.0
    retry_count: int = 1
    log_level: str = "INFO"
    synthetic_grid_export_enabled: bool = False
    synthetic_grid_total_power_w: int = -4500
    synthetic_grid_voltage_l1_v: float = 229.4
    synthetic_grid_voltage_l2_v: float = 230.1
    synthetic_grid_voltage_l3_v: float = 230.5
    synthetic_grid_frequency_hz: float = 50.0


@dataclass
class FroniusConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 502
    slave_id: int = 1
    pv_string_count: int = 2
    sunspec_model_160_enabled: bool = True
    timeout: float = 1.0
    retry_count: int = 1
    log_level: str = "INFO"
    synthetic_pv_enabled: bool = False
    synthetic_pv_total_power_w: int = 8200
    synthetic_pv1_voltage_v: float = 500.0
    synthetic_pv2_voltage_v: float = 500.0


@dataclass
class VictronConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 502
    slave_id: int = 100
    timeout: float = 1.0
    retry_count: int = 1
    log_level: str = "INFO"
    battery_scale: float = 1.0
    battery_voltage_min_v: float = 0.0
    battery_voltage_max_v: float = 1000.0


@dataclass
class GoodweEmulatorConfig:
    bind_host: str = "0.0.0.0"
    rtu_port: int = 8899
    socket_port: int = 8898
    comm_addr: int = 254
    update_interval: float = 1.0
    data_timeout: float = 5.0
    log_level: str = "INFO"
    serial_number: str = "ETEMU00000001"
    model_name: str = "GW10K-ET"
    external_model_name: str = "EM540+Fronius+Victron"
    rated_power: int = 10000


@dataclass
class RootConfig:
    log_level: str = "INFO"


@dataclass
class AppConfig:
    em540_bridge: Em540BridgeConfig = field(default_factory=Em540BridgeConfig)
    fronius: FroniusConfig = field(default_factory=FroniusConfig)
    victron: VictronConfig = field(default_factory=VictronConfig)
    goodwe_emulator: GoodweEmulatorConfig = field(default_factory=GoodweEmulatorConfig)
    root: RootConfig = field(default_factory=RootConfig)


REQUIRED_SECTIONS = ("em540_bridge", "fronius", "victron", "goodwe_emulator", "root")
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigManager:
    def __init__(self, path: str) -> None:
        self._path = path

    def load(self) -> AppConfig:
        data = self._read_yaml(self._path)
        for section in REQUIRED_SECTIONS:
            if section not in data:
                raise ConfigError(f"Missing required config section: {section}")

        cfg = AppConfig()
        self._update_dataclass(cfg.em540_bridge, data.get("em540_bridge", {}))
        self._update_dataclass(cfg.fronius, data.get("fronius", {}))
        self._update_dataclass(cfg.victron, data.get("victron", {}))
        self._update_dataclass(cfg.goodwe_emulator, data.get("goodwe_emulator", {}))
        self._update_dataclass(cfg.root, data.get("root", {}))
        self._validate(cfg)
        return cfg

    @staticmethod
    def _read_yaml(path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {path}")
        try:
            data = yaml.safe_load(p.read_text())
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("Config YAML must be a mapping")
        return data

    @staticmethod
    def _update_dataclass(obj: Any, raw: dict[str, Any]) -> None:
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

    @staticmethod
    def _validate(cfg: AppConfig) -> None:
        for port in [
            cfg.em540_bridge.port,
            cfg.fronius.port,
            cfg.victron.port,
            cfg.goodwe_emulator.rtu_port,
            cfg.goodwe_emulator.socket_port,
        ]:
            if not (0 < int(port) < 65535):
                raise ConfigError(f"Invalid port value: {port}")

        if int(cfg.goodwe_emulator.rtu_port) == int(cfg.goodwe_emulator.socket_port):
            raise ConfigError("goodwe_emulator.rtu_port and goodwe_emulator.socket_port must differ")

        if float(cfg.goodwe_emulator.update_interval) <= 0:
            raise ConfigError(f"Invalid goodwe_emulator.update_interval: {cfg.goodwe_emulator.update_interval}")

        if float(cfg.goodwe_emulator.data_timeout) <= 0:
            raise ConfigError(f"Invalid goodwe_emulator.data_timeout: {cfg.goodwe_emulator.data_timeout}")

        for slave_id in [
            cfg.em540_bridge.slave_id,
            cfg.fronius.slave_id,
            cfg.victron.slave_id,
            cfg.goodwe_emulator.comm_addr,
        ]:
            if not (0 < int(slave_id) < 256):
                raise ConfigError(f"Invalid slave_id value: {slave_id}")

        level = str(cfg.root.log_level).upper()
        if level not in VALID_LOG_LEVELS:
            raise ConfigError(f"Invalid root.log_level: {cfg.root.log_level}")
        cfg.root.log_level = level

        service_levels = {
            "em540_bridge.log_level": cfg.em540_bridge.log_level,
            "fronius.log_level": cfg.fronius.log_level,
            "victron.log_level": cfg.victron.log_level,
            "goodwe_emulator.log_level": cfg.goodwe_emulator.log_level,
        }
        for key, value in service_levels.items():
            level = str(value).upper()
            if level not in VALID_LOG_LEVELS:
                raise ConfigError(f"Invalid {key}: {value}")

        cfg.em540_bridge.log_level = str(cfg.em540_bridge.log_level).upper()
        cfg.fronius.log_level = str(cfg.fronius.log_level).upper()
        cfg.victron.log_level = str(cfg.victron.log_level).upper()
        cfg.goodwe_emulator.log_level = str(cfg.goodwe_emulator.log_level).upper()

        retry_counts = {
            "em540_bridge.retry_count": cfg.em540_bridge.retry_count,
            "fronius.retry_count": cfg.fronius.retry_count,
            "victron.retry_count": cfg.victron.retry_count,
        }
        for key, value in retry_counts.items():
            if int(value) < 0:
                raise ConfigError(f"Invalid {key}: {value}")

        cfg.em540_bridge.retry_count = int(cfg.em540_bridge.retry_count)
        cfg.fronius.retry_count = int(cfg.fronius.retry_count)
        cfg.victron.retry_count = int(cfg.victron.retry_count)

        if float(cfg.victron.battery_scale) <= 0:
            raise ConfigError(f"Invalid victron.battery_scale: {cfg.victron.battery_scale}")

        min_v = float(cfg.victron.battery_voltage_min_v)
        max_v = float(cfg.victron.battery_voltage_max_v)
        if min_v < 0:
            raise ConfigError(f"Invalid victron.battery_voltage_min_v: {cfg.victron.battery_voltage_min_v}")
        if max_v <= min_v:
            raise ConfigError(f"Invalid victron.battery_voltage_max_v: {cfg.victron.battery_voltage_max_v}")


def load_config(config_path: str) -> AppConfig:
    return ConfigManager(config_path).load()
