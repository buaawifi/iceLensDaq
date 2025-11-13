from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from time import sleep
from importlib import import_module
from loguru import logger

# --- Detect client import path (3.x vs 2.x) ---
try:
    from pymodbus.client import ModbusSerialClient  # 3.x
    PM_VER = "3.x"
except Exception:  # pragma: no cover
    from pymodbus.client.sync import ModbusSerialClient  # 2.x
    PM_VER = "2.x"

# --- Try to import the enum FramerType (3.x style). Some releases expose it at root. ---
_FrType = None
try:
    # Preferred in many 3.x builds
    from pymodbus import FramerType as _FrType  # type: ignore[attr-defined]
except Exception:
    try:
        # Some builds expose it here
        from pymodbus.framer import FramerType as _FrType  # type: ignore[attr-defined]
    except Exception:
        _FrType = None

# Modbus Parity options
PARITY = {"N": "N", "E": "E", "O": "O"}

@dataclass
class BusSpec:
    """
    Represents the configuration parameters for a Modbus communication bus.

    Attributes:
        port (str): The serial port to use for communication (e.g., COM1, /dev/ttyS0).
        baud (int): The baud rate for communication (default is 9600).
        parity (str): The parity bit for error checking (default is 'N' for None).
        stopbits (int): The number of stop bits used in communication (default is 1).
        bytesize (int): The number of data bits in each byte (default is 8).
        timeout_ms (int): The timeout period in milliseconds for client operations (default is 200ms).
    """
    port: str
    baud: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout_ms: int = 200

def _build_client(spec: BusSpec) -> ModbusSerialClient:
    """
    Builds and returns a ModbusSerialClient based on the given BusSpec configuration.
    Handles compatibility with different versions of `pymodbus` (3.x vs 2.x).

    Args:
        spec (BusSpec): The Modbus bus specification (port, baud, parity, etc.).

    Returns:
        ModbusSerialClient: A configured Modbus client instance.

    Notes:
        - 2.x uses method="rtu".
        - 3.x prefers using framer=FramerType.RTU (enum). If not available, it falls back to "rtu".
    """
    if PM_VER == "2.x":
        return ModbusSerialClient(
            method="rtu",
            port=spec.port,
            baudrate=spec.baud,
            parity=PARITY.get(spec.parity.upper(), "N"),
            stopbits=spec.stopbits,
            bytesize=spec.bytesize,
            timeout=spec.timeout_ms / 1000.0,
        )

    # 3.x path (keyword-only params per 3.8+ API changes)
    common = dict(
        port=spec.port,
        baudrate=spec.baud,
        parity=PARITY.get(spec.parity.upper(), "N"),
        stopbits=spec.stopbits,
        bytesize=spec.bytesize,
        timeout=spec.timeout_ms / 1000.0,
    )
    if _FrType is not None:  # enum present
        logger.debug("Using framer=FramerType.RTU")
        return ModbusSerialClient(framer=_FrType.RTU, **common)  # type: ignore[arg-type]

    # last resort: some 3.x builds accept string name
    logger.debug('Using framer="rtu" (enum not found)')
    return ModbusSerialClient(framer="rtu", **common)

class ModbusBus:
    """
    Represents a Modbus communication bus for interacting with Modbus devices.

    Attributes:
        name (str): The name of the bus (e.g., 'control_bus', 'daq_bus').
        spec (BusSpec): The configuration parameters for the bus (e.g., port, baud rate).
        client (Optional[ModbusSerialClient]): The Modbus client instance for communication.
        ok (bool): Indicates if the bus is successfully connected.

    Methods:
        open():
            Opens the Modbus connection using the specified bus configuration.
        close():
            Closes the Modbus connection if it is open.
        read_input(unit: int, address: int, count: int = 1):
            Reads input registers from the Modbus bus.
        read_holding(unit: int, address: int, count: int = 1):
            Reads holding registers from the Modbus bus.
        write_holding(unit: int, address: int, value: int):
            Writes a value to a holding register on the Modbus bus.
        try_until_ok(fn, retries=1, delay=0.05, *a, **kw):
            Attempts to call a function repeatedly until successful or retries are exhausted.
    """
    
    def __init__(self, name: str, spec: BusSpec):
        """
        Initializes the ModbusBus instance with the given name and bus configuration.

        Args:
            name (str): The name of the Modbus bus (e.g., 'control_bus').
            spec (BusSpec): The configuration for the Modbus bus (e.g., port, baud rate).
        """
        self.name = name
        self.spec = spec
        self.client: Optional[ModbusSerialClient] = None
        self.ok = False

    def open(self):
        """
        Opens the Modbus connection using the specified bus configuration.
        If the connection is successful, sets `self.ok` to True.

        Logs the connection attempt and success/failure.
        """
        self.client = _build_client(self.spec)
        self.ok = bool(self.client.connect())
        logger.info(f"[{self.name}] open {self.spec.port} (pymodbus {PM_VER}) -> {self.ok}")

    def close(self):
        """
        Closes the Modbus connection if it is open.

        Sets `self.ok` to False once the connection is closed.
        """
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.ok = False

    # --- helpers (standardize on unit= for 3.x; also valid in late 2.x) ---
    def read_input(self, unit: int, address: int, count: int = 1):
        """
        Reads input registers from the Modbus client.

        Args:
            unit (int): The Modbus unit identifier (e.g., device address).
            address (int): The starting address of the register to read.
            count (int): The number of registers to read (default is 1).

        Returns:
            list: A list of register values if successful, or None if the client is not connected.
        """
        if not self.ok:
            return None
        rr = self.client.read_input_registers(address=address, count=count, unit=unit)
        return getattr(rr, "registers", None)

    def read_holding(self, unit: int, address: int, count: int = 1):
        """
        Reads holding registers from the Modbus client.

        Args:
            unit (int): The Modbus unit identifier (e.g., device address).
            address (int): The starting address of the register to read.
            count (int): The number of registers to read (default is 1).

        Returns:
            list: A list of register values if successful, or None if the client is not connected.
        """
        if not self.ok:
            return None
        rr = self.client.read_holding_registers(address=address, count=count, unit=unit)
        return getattr(rr, "registers", None)

    def write_holding(self, unit: int, address: int, value: int):
        """
        Writes a value to a holding register on the Modbus client.

        Args:
            unit (int): The Modbus unit identifier (e.g., device address).
            address (int): The address of the register to write to.
            value (int): The value to write to the register.

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        if not self.ok:
            return False
        rq = self.client.write_register(address=address, value=value, unit=unit)
        return getattr(rq, "isError", lambda: True)() is False

    def try_until_ok(self, fn, retries=1, delay=0.05, *a, **kw):
        """
        Attempts to call a function repeatedly until successful or retries are exhausted.

        Args:
            fn (function): The function to call.
            retries (int): The number of retries to attempt (default is 1).
            delay (float): The delay between retries in seconds (default is 0.05).
            *a, **kw: Arguments passed to the function `fn`.

        Returns:
            Any: The result of the function call if successful, or None if all retries fail.
        """
        for _ in range(max(1, retries)):
            try:
                out = fn(*a, **kw)
                if out is not None:
                    return out
            except Exception as e:
                from time import sleep
                logger.debug(f"[{self.name}] try_until_ok error: {e}")
            sleep(delay)
        return None
