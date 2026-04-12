import tempfile
from pathlib import Path

import pytest

from app.config import ConfigError, load_config

VALID_CONFIG = """
em540_bridge:
  enabled: true
  host: 127.0.0.1
  port: 5001
  slave_id: 1
  timeout: 1.0
  log_level: INFO
fronius:
  enabled: true
  host: 127.0.0.1
  port: 502
  slave_id: 1
  pv_string_count: 2
  sunspec_model_160_enabled: true
  timeout: 2.0
  log_level: INFO
victron:
  enabled: true
  host: 127.0.0.1
  port: 502
  slave_id: 100
  timeout: 1.0
  log_level: INFO
goodwe_emulator:
  bind_host: 0.0.0.0
  bind_port: 8899
  comm_addr: 254
  update_interval: 1.0
  data_timeout: 5.0
  log_level: INFO
  serial_number: ETEMU00000001
  model_name: GW10K-ET
  rated_power: 10000
root:
  log_level: INFO
"""


def test_load_valid_config():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.yaml"
        p.write_text(VALID_CONFIG)
        cfg = load_config(str(p))
        assert cfg.goodwe_emulator.bind_port == 8899


def test_missing_required_section_raises_error():
    bad = VALID_CONFIG.replace(
        "fronius:\n"
        "  enabled: true\n"
        "  host: 127.0.0.1\n"
        "  port: 502\n"
        "  slave_id: 1\n"
        "  pv_string_count: 2\n"
        "  sunspec_model_160_enabled: true\n"
        "  timeout: 2.0\n",
        "",
    )
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.yaml"
        p.write_text(bad)
        with pytest.raises(ConfigError, match="fronius"):
            load_config(str(p))


def test_invalid_port_raises_error():
    bad = VALID_CONFIG.replace("bind_port: 8899", "bind_port: 70000")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.yaml"
        p.write_text(bad)
        with pytest.raises(ConfigError, match="Invalid port"):
            load_config(str(p))

def test_invalid_data_timeout_raises_error():
    bad = VALID_CONFIG.replace("data_timeout: 5.0", "data_timeout: 0")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.yaml"
        p.write_text(bad)
        with pytest.raises(ConfigError, match="data_timeout"):
            load_config(str(p))
