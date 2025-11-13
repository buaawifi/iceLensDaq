from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
from time import sleep
from loguru import logger
import inspect

try:
    from pymodbus.client import ModbusSerialClient  # pymodbus 3.x+
    PM_VER = "3.x+"
except Exception:  # pragma: no cover
    from pymodbus.client.sync import ModbusSerialClient  # pymodbus 2.x
    PM_VER = "2.x"


@dataclass
class BusSpec:
    port: str
    baud: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout_ms: int = 200


class ModbusBus:
    def __init__(self, name: str, spec: BusSpec):
        self.name = name
        self.spec = spec
        self.client: Optional[ModbusSerialClient] = None
        self.ok: bool = False
        self._addr_kw: Optional[str] = None  # "unit", "slave" or "device_id"

    # --- connection management ---
    def _build_client(self) -> ModbusSerialClient:
        timeout_s = max(self.spec.timeout_ms, 50) / 1000.0
        client = ModbusSerialClient(
            port=self.spec.port,
            baudrate=self.spec.baud,
            bytesize=self.spec.bytesize,
            parity=self.spec.parity,
            stopbits=self.spec.stopbits,
            timeout=timeout_s,
            # method="rtu",   # ok for 2.x, accepted/ignored in 3.x+
        )
        return client

    def open(self) -> bool:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass

        self.client = self._build_client()
        try:
            self.ok = bool(self.client.connect())
        except Exception as e:  # pragma: no cover
            logger.error(f"[{self.name}] connect error on {self.spec.port}: {e}")
            self.ok = False

        logger.info(f"[{self.name}] open {self.spec.port} (pymodbus {PM_VER}) -> {self.ok}")

        if self.ok:
            self._detect_addr_kw()

        return self.ok

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.ok = False

    # --- helpers ---
    def _detect_addr_kw(self):
        """
        Detect which keyword the client expects for the unit id.
        Newer pymodbus uses ``device_id`` or ``slave`` instead of ``unit``.
        """
        fn = getattr(self.client, "read_holding_registers", None)
        if fn is None:
            self._addr_kw = None
            return

        try:
            sig = inspect.signature(fn)
            for cand in ("unit", "slave", "device_id"):
                if cand in sig.parameters:
                    self._addr_kw = cand
                    break
        except Exception:
            self._addr_kw = "unit"

    def _call_read(self, which: str, unit: int, address: int, count: int = 1) -> Optional[List[int]]:
        if not self.ok or self.client is None:
            return None

        fn_name = "read_input_registers" if which == "input" else "read_holding_registers"
        fn = getattr(self.client, fn_name, None)
        if fn is None:
            logger.error(f"[{self.name}] client has no {fn_name}")
            return None

        # First try keyword-based call
        if self._addr_kw:
            kwargs = {"address": address, "count": count, self._addr_kw: unit}
            try:
                rr = fn(**kwargs)
            except TypeError as e:
                logger.debug(f"[{self.name}] {fn_name} kw call failed ({e}), retrying positional.")
                rr = None
            except Exception as e:
                logger.debug(f"[{self.name}] {fn_name} error: {e}")
                return None
        else:
            rr = None

        # Fallback to positional (old 2.x style)
        if rr is None:
            try:
                rr = fn(address, count, unit)
            except Exception as e:
                logger.debug(f"[{self.name}] {fn_name} positional error: {e}")
                return None

        if not rr or getattr(rr, "isError", lambda: True)():
            return None

        return getattr(rr, "registers", None)

    def _call_write(self, unit: int, address: int, value: int) -> bool:
        if not self.ok or self.client is None:
            return False

        fn = getattr(self.client, "write_register", None)
        if fn is None:
            logger.error(f"[{self.name}] client has no write_register")
            return False

        if self._addr_kw:
            kwargs = {"address": address, "value": value, self._addr_kw: unit}
            try:
                rq = fn(**kwargs)
            except TypeError as e:
                logger.debug(f"[{self.name}] write_register kw call failed ({e}), retrying positional.")
                rq = None
            except Exception as e:
                logger.debug(f"[{self.name}] write_register error: {e}")
                return False
        else:
            rq = None

        if rq is None:
            try:
                rq = fn(address, value, unit)
            except Exception as e:
                logger.debug(f"[{self.name}] write_register positional error: {e}")
                return False

        return getattr(rq, "isError", lambda: True)() is False

    # --- public API used by drivers ---
    def read_input(self, unit: int, address: int, count: int = 1) -> Optional[List[int]]:
        return self._call_read("input", unit, address, count)

    def read_holding(self, unit: int, address: int, count: int = 1) -> Optional[List[int]]:
        return self._call_read("holding", unit, address, count)

    def write_holding(self, unit: int, address: int, value: int) -> bool:
        return self._call_write(unit, address, value)

    def try_until_ok(self, fn, retries: int = 1, delay: float = 0.05, *a, **kw):
        for _ in range(max(1, retries)):
            try:
                out = fn(*a, **kw)
                if out is not None:
                    return out
            except Exception as e:
                logger.debug(f"[{self.name}] try_until_ok error: {e}")
            sleep(delay)
        return None
