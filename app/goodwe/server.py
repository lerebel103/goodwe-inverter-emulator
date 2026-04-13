from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping

from pymodbus import FramerType
from pymodbus.constants import ExcCodes
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.pdu import ModbusPDU
from pymodbus.server import StartTcpServer

logger = logging.getLogger(__name__)


class _CircuitBreaker:
    def __init__(self, timeout: float):
        self._timeout = timeout
        self._last_success_monotonic: float | None = None
        self._open = True
        self._open_count = 1
        self._dropped_request_count = 0
        self._last_warning_monotonic = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def mark_success(self) -> None:
        with self._lock:
            self._last_success_monotonic = time.monotonic()
            was_open = self._open
            if self._open:
                self._open = False

        if was_open:
            logger.info("Closing Modbus circuit breaker: fresh upstream data")

    def mark_failure(self) -> None:
        stale_age = self.stale_age_seconds()
        if stale_age is None:
            # No successful snapshot has been published yet, so remain open.
            self._open_circuit("upstream read failure")
            return

        # Intermittent upstream failures are tolerated while cached data is fresh.
        if stale_age > self._timeout:
            self._open_circuit("upstream read failure")

    def stale_age_seconds(self) -> float | None:
        with self._lock:
            if self._last_success_monotonic is None:
                return None
            return time.monotonic() - self._last_success_monotonic

    def allow_datastore_access(self) -> bool:
        stale_age = self.stale_age_seconds()
        if stale_age is None or stale_age > self._timeout:
            self._open_circuit("stale upstream data")

        with self._lock:
            if not self._open:
                return True

            self._dropped_request_count += 1
            dropped = self._dropped_request_count
            now = time.monotonic()
            should_warn = now - self._last_warning_monotonic > 10.0
            if should_warn:
                self._last_warning_monotonic = now

        if should_warn:
            logger.warning(
                "Dropping downstream request while circuit open; dropped=%d stale_age=%s",
                dropped,
                "none" if stale_age is None else f"{stale_age:.3f}s",
            )
        return False

    def _open_circuit(self, reason: str) -> None:
        with self._lock:
            should_log = not self._open
            if should_log:
                self._open = True
                self._open_count += 1

        if should_log:
            logger.warning("Opening Modbus circuit breaker: %s", reason)


class GoodweModbusServer:
    def __init__(self, bind_host: str, rtu_port: int, socket_port: int, comm_addr: int, data_timeout: float):
        self._bind_host = bind_host
        self._rtu_port = rtu_port
        self._socket_port = socket_port
        self._comm_addr = comm_addr
        self._lock = threading.Lock()
        self._breaker = _CircuitBreaker(data_timeout)
        self._store = ModbusDeviceContext(hr=_BreakerDataBlock(0, [0] * 50000, self._breaker))
        # Keep unit 1 available for tooling in addition to configured GoodWe comm address.
        self._context = ModbusServerContext(devices={self._comm_addr: self._store, 0x01: self._store}, single=False)

    @staticmethod
    def _trace_connect(connected: bool) -> None:
        if connected:
            logger.info("Modbus/TCP client connected")
        else:
            logger.info("Modbus/TCP client disconnected")

    def _trace_pdu(self, sending: bool, pdu: ModbusPDU) -> ModbusPDU:
        if not sending:
            logger.debug(
                "RX fc=%s dev=%s addr=%s count=%s",
                getattr(pdu, "function_code", "?"),
                getattr(pdu, "dev_id", "?"),
                getattr(pdu, "address", "?"),
                getattr(pdu, "count", "?"),
            )
            return pdu

        logger.debug(
            "TX fc=%s dev=%s regs=%s payload=%s",
            getattr(pdu, "function_code", "?"),
            getattr(pdu, "dev_id", "?"),
            len(getattr(pdu, "registers", [])),
            getattr(pdu, "registers", None),
        )
        return pdu

    def mark_data_received(self) -> None:
        self._breaker.mark_success()

    def mark_upstream_failed(self) -> None:
        self._breaker.mark_failure()

    def update_holding_registers(self, values: Mapping[int, int]) -> None:
        with self._lock:
            for addr, value in values.items():
                if 0 <= addr < 50000:
                    self._store.setValues(3, addr, [int(value) & 0xFFFF])

    def _serve(self, framer: FramerType, port: int, label: str) -> None:
        logger.info(
            "Starting GoodWe ET emulator Modbus/TCP server on %s:%s (%s framer)",
            self._bind_host,
            port,
            label,
        )
        StartTcpServer(
            context=self._context,
            address=(self._bind_host, port),
            framer=framer,
            ignore_missing_devices=False,
            trace_connect=self._trace_connect,
            trace_pdu=self._trace_pdu,
        )

    def serve_forever(self) -> None:
        rtu_thread = threading.Thread(
            target=self._serve,
            args=(FramerType.RTU, self._rtu_port, "RTU"),
            name="goodwe-modbus-rtu",
            daemon=True,
        )
        rtu_thread.start()

        # Keep socket-framed listener on the main thread.
        self._serve(FramerType.SOCKET, self._socket_port, "SOCKET")


class _BreakerDataBlock(ModbusSequentialDataBlock):
    def __init__(self, address: int, values: list[int], breaker: _CircuitBreaker):
        super().__init__(address, values)
        self._breaker = breaker

    def getValues(self, address, count=1):  # noqa: N802 - pymodbus API name
        if not self._breaker.allow_datastore_access():
            return ExcCodes.DEVICE_BUSY
        return super().getValues(address, count)
