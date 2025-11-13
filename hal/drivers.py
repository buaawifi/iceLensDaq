from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from loguru import logger

# --- Address helpers for vendors that publish "30xxx/40xxx" style tables ---
def reg3x_to_offset(addr_3x: int) -> int:
    """
    Converts a Modbus 3x register address to an offset.

    Modbus 3x registers are typically addressed starting at 30001,
    but we convert this into an offset that starts at 0.

    Args:
        addr_3x (int): The 3x register address (e.g., 30001, 30002, etc.).

    Returns:
        int: The offset corresponding to the provided 3x address.
    """
    return max(0, addr_3x - 30001)

def reg4x_to_offset(addr_4x: int) -> int:
    """
    Converts a Modbus 4x register address to an offset.

    Modbus 4x registers are typically addressed starting at 40001,
    but we convert this into an offset that starts at 0.

    Args:
        addr_4x (int): The 4x register address (e.g., 40001, 40002, etc.).

    Returns:
        int: The offset corresponding to the provided 4x address.
    """
    return max(0, addr_4x - 40001)

# === Base device ===
@dataclass
class BaseDev:
    """
    A base class representing a Modbus device with common properties.

    Attributes:
        name (str): The name of the device.
        bus (any): The Modbus communication bus associated with this device (e.g., ModbusBus).
        unit (int): The Modbus unit address (e.g., slave address of the device).
    """
    name: str
    bus: any          # ModbusBus
    unit: int         # modbus address

# === AI device (e.g., DAM-3158A) ===
class AI(BaseDev):
    """
    A class representing an Analog Input (AI) device.

    For example, the DAM-3158A module.

    Attributes:
        CH0_3X (int): The base register address for channel 0 (e.g., 30257).

    Methods:
        read_channel(ch: int) -> Optional[int]:
            Reads a specific channel on the AI device.
    """
    # CH0 at 30257, so 30257 - 30001 = 256
    CH0_3X = 30257

    def read_channel(self, ch: int) -> Optional[int]:
        """
        Reads the value of a specific channel on the AI device.

        Args:
            ch (int): The channel number to read (e.g., 0, 1, 2, etc.).

        Returns:
            Optional[int]: The value of the channel, or None if reading fails.
        """
        off = reg3x_to_offset(self.CH0_3X) + ch
        regs = self.bus.read_input(self.unit, off, 1)
        return None if regs is None else regs[0]

# === TDA thermocouple device (DAM-3130D H or similar) ===
class TDA(BaseDev):
    """
    A class representing a Thermocouple Device (e.g., DAM-3130D H).

    Attributes:
        (Additional attributes can be added here depending on the device specifications.)

    Methods:
        (Methods for reading temperature channels or other thermocouple-specific logic can be added here.)
    """
    # assume channel n at 0-based input register n-1 (adjust if your device is different)
    def read_channel(self, ch: int) -> Optional[int]:
        """
        Reads the value of a specific channel on the TDA device.

        Args:
            ch (int): The channel number to read (e.g., 1, 2, 3, etc.).

        Returns:
            Optional[int]: The value of the channel, or None if reading fails.
        """
        off = max(0, ch - 1)
        regs = self.bus.read_input(self.unit, off, 1)
        return None if regs is None else regs[0]

# === AO analog output (0-10V) ===
class AO(BaseDev):
    """
    A class representing an Analog Output (AO) device.

    For example, an output module that controls a 0-10V signal.

    Attributes:
        CH1_4X (int): The base register address for channel 1 (e.g., 0x000A).

    Methods:
        write_voltage_fixed3(ch: int, volts: float, reg_scale: int = 1000) -> bool:
            Writes a fixed voltage value (scaled to the register's range).
        write_percent_to_0_10v(ch: int, percent: float, reg_scale: int = 1000) -> bool:
            Writes a voltage value based on a percentage (0-100%).
    """
    # CH1 at 0x000A, CHn = base + (n-1)
    CH1_4X = 0x000A

    def write_voltage_fixed3(self, ch: int, volts: float, reg_scale: int = 1000) -> bool:
        """
        Writes a fixed voltage value to an AO channel, scaling the input to match the register format.

        Args:
            ch (int): The channel number to write to (e.g., 1, 2, etc.).
            volts (float): The voltage to write (e.g., 0.0 to 10.0).
            reg_scale (int): The scaling factor for the voltage (default is 1000).

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        volts = max(0.0, min(10.0, float(volts)))  # Ensure the voltage is within the allowed range
        raw   = int(round(volts * reg_scale))      # Scale the voltage to the register format
        off = (self.CH1_4X + (ch - 1))
        return self.bus.write_holding(self.unit, off, raw)

    def write_percent_to_0_10v(self, ch: int, percent: float, reg_scale: int = 1000) -> bool:
        """
        Writes a voltage value based on a percentage (0-100%).

        Args:
            ch (int): The channel number to write to (e.g., 1, 2, etc.).
            percent (float): The percentage value (e.g., 0 to 100%).
            reg_scale (int): The scaling factor for the voltage (default is 1000).

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        pct = max(0.0, min(100.0, float(percent)))  # Ensure the percentage is within the valid range
        return self.write_voltage_fixed3(ch, pct * 0.10, reg_scale)

# === PPS programmable power supply (percent command) ===
class PPS(BaseDev):
    """
    A class representing a Programmable Power Supply (PPS).

    Attributes:
        CMD_4X (int): The base register address for the command (e.g., 0x0001).

    Methods:
        write_percent(percent: float) -> bool:
            Writes a percentage value to the PPS command register.
    """
    # common pattern: cmd at 0x0001, fb at 0x1001 (confirm against your handbook)
    CMD_4X = 0x0001

    def write_percent(self, percent: float) -> bool:
        """
        Writes a percentage command to the PPS device.

        Args:
            percent (float): The percentage value to write (e.g., 0.0 to 100%).

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        pct = max(0.0, min(100.0, float(percent)))  # Ensure the percentage is within the valid range
        value = int(round(pct))   # Many PPS devices expect an integer percent value
        return self.bus.write_holding(self.unit, self.CMD_4X, value)

# === Cryogenic pump (percent speed) ===
class Pump(BaseDev):
    """
    A class representing a Cryogenic Pump device.

    Attributes:
        CMD_4X (int): The base register address for the command (e.g., 0x0001).

    Methods:
        write_percent(percent: float) -> bool:
            Writes a percentage value to the pump's speed register.
    """
    CMD_4X = 0x0001

    def write_percent(self, percent: float) -> bool:
        """
        Writes a percentage value to control the speed of the cryogenic pump.

        Args:
            percent (float): The percentage value to set the pump speed (e.g., 0.0 to 100%).

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        pct = max(0.0, min(100.0, float(percent)))  # Ensure the percentage is within the valid range
        value = int(round(pct))
        return self.bus.write_holding(self.unit, self.CMD_4X, value)

# === Factory ===
def make_device(dev_name: str, dev_cfg: dict, bus) -> BaseDev:
    """
    Factory function to create and return a device instance based on the provided configuration.

    Args:
        dev_name (str): The name of the device.
        dev_cfg (dict): The device configuration containing type and address.
        bus (ModbusBus): The Modbus bus instance for communication.

    Returns:
        BaseDev: An instance of the device class (AI, TDA, AO, PPS, Pump).

    Raises:
        ValueError: If an unknown device type is provided.
    """
    t = dev_cfg["type"].upper()  # Get the device type (AI, TDA, etc.)
    unit = int(dev_cfg["addr"])  # Get the device's Modbus address
    if   t == "AI":   return AI(dev_name, bus, unit)
    elif t == "TDA":  return TDA(dev_name, bus, unit)
    elif t == "AO":   return AO(dev_name, bus, unit)
    elif t == "PPS":  return PPS(dev_name, bus, unit)
    elif t == "PUMP": return Pump(dev_name, bus, unit)
    else:
        raise ValueError(f"Unknown device type: {t}")
