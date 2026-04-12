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


class PersistentModbusSession:
    """Maintain a persistent Modbus client with reconnect-on-failure semantics."""

    def __init__(
        self,
        *,
        source_name: str,
        create_client: Callable[[], Any],
        breaker: ModbusClientCircuitBreaker,
        retries: int = 1,
    ):
        self._source_name = source_name
        self._create_client = create_client
        self._breaker = breaker
        self._retries = max(1, int(retries) + 1)
        self._client: Any | None = None
        self._lock = threading.Lock()

    def read(self, read_once: Callable[[Any], dict[str, float | int]]) -> dict[str, float | int]:
        with self._lock:
            if not self._breaker.allow_request():
                logger.debug("Skipping %s Modbus read while breaker is cooling down", self._source_name)
                return {}

            last_error = "unknown failure"
            for attempt in range(1, self._retries + 1):
                if not self._ensure_connected():
                    last_error = "connect() returned false"
                    logger.warning(
                        "%s Modbus connect failed on attempt %d/%d",
                        self._source_name,
                        attempt,
                        self._retries,
                    )
                    continue

                try:
                    payload = read_once(self._client)
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "%s Modbus read attempt %d/%d failed with exception: %s",
                        self._source_name,
                        attempt,
                        self._retries,
                        last_error,
                    )
                    self._close_and_reset()
                    continue

                if not payload:
                    last_error = "empty payload"
                    logger.warning(
                        "%s Modbus read returned empty payload on attempt %d/%d",
                        self._source_name,
                        attempt,
                        self._retries,
                    )
                    self._close_and_reset()
                    continue

                self._breaker.mark_success()
                return payload

            self._breaker.mark_failure(last_error)
            return {}

    def _ensure_connected(self) -> bool:
        if self._client is not None and self._is_connected(self._client):
            return True

        if self._client is None:
            self._client = self._create_client()

        try:
            connected = bool(self._client.connect())
        except Exception:
            connected = False

        if connected:
            setattr(self._client, "_persistent_connected", True)
            return True

        self._close_and_reset()
        return False

    @staticmethod
    def _is_connected(client: Any) -> bool:
        if bool(getattr(client, "_persistent_connected", False)):
            return True

        connected_attr = getattr(client, "connected", None)
        if isinstance(connected_attr, bool):
            return connected_attr
        return False

    def _close_and_reset(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.debug("%s Modbus close failed", self._source_name, exc_info=True)
            finally:
                self._client = None


def read_modbus_payload_with_recovery(
    *,
    source_name: str,
    create_client: Callable[[], Any],
    read_once: Callable[[Any], dict[str, float | int]],
    breaker: ModbusClientCircuitBreaker,
    retries: int = 1,
) -> dict[str, float | int]:
    """Read a payload with reconnect retry and guaranteed disconnect on all paths."""
    # Backward-compatible one-shot helper built on persistent session semantics.
    session = PersistentModbusSession(
        source_name=source_name,
        create_client=create_client,
        breaker=breaker,
        retries=retries,
    )
    return session.read(read_once)
