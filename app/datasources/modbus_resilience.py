from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ModbusClientCircuitBreaker:
    """Simple cooldown breaker to avoid flooding dead upstream Modbus endpoints."""

    def __init__(self, name: str, *, failure_threshold: int = 3, cooldown_seconds: float = 5.0):
        self._name = name
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_seconds = max(0.1, float(cooldown_seconds))
        self._consecutive_failures = 0
        self._opened_until_monotonic = 0.0
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        with self._lock:
            now = time.monotonic()
            return now >= self._opened_until_monotonic

    def mark_success(self) -> None:
        with self._lock:
            was_open = time.monotonic() < self._opened_until_monotonic
            self._consecutive_failures = 0
            self._opened_until_monotonic = 0.0

        if was_open:
            logger.info("%s circuit breaker closed after successful recovery", self._name)

    def mark_failure(self, reason: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures < self._failure_threshold:
                return

            self._opened_until_monotonic = time.monotonic() + self._cooldown_seconds
            failures = self._consecutive_failures

        logger.warning(
            "%s circuit breaker open for %.1fs after %d failures (%s)",
            self._name,
            self._cooldown_seconds,
            failures,
            reason,
        )


def read_modbus_payload_with_recovery(
    *,
    source_name: str,
    create_client: Callable[[], Any],
    read_once: Callable[[Any], dict[str, float | int]],
    breaker: ModbusClientCircuitBreaker,
    retries: int = 1,
) -> dict[str, float | int]:
    """Read a payload with reconnect retry and guaranteed disconnect on all paths."""

    if not breaker.allow_request():
        logger.debug("Skipping %s Modbus read while breaker is cooling down", source_name)
        return {}

    max_attempts = max(1, int(retries) + 1)
    last_error = "unknown failure"

    for attempt in range(1, max_attempts + 1):
        client: Any | None = None
        try:
            client = create_client()
            if not client.connect():
                last_error = "connect() returned false"
                logger.warning(
                    "%s Modbus connect failed on attempt %d/%d",
                    source_name,
                    attempt,
                    max_attempts,
                )
                continue

            payload = read_once(client)
            if not payload:
                last_error = "empty payload"
                logger.warning(
                    "%s Modbus read returned empty payload on attempt %d/%d",
                    source_name,
                    attempt,
                    max_attempts,
                )
                continue

            breaker.mark_success()
            return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "%s Modbus read attempt %d/%d failed with exception: %s",
                source_name,
                attempt,
                max_attempts,
                last_error,
            )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    logger.debug("%s Modbus close failed", source_name, exc_info=True)

    breaker.mark_failure(last_error)
    return {}
