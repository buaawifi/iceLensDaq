from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from loguru import logger


# --- Address helpers for "30xxx/40xxx" style tables ---
def reg3x_to_offset(addr_3x: int) -> int:
    """Convert a 3x address (30001-based) to zero-based offset."""
    return max(0, addr_3x - 30001)


def reg4x_to_offset(addr_4x: int) -> int:
    """Convert a 4x address (40001-based) to zero-based offset."""
    return max(0, addr_4x - 40001)


# === Base device ===
@dataclass
class BaseDev:
    name: str
    bus: any          # ModbusBus
    unit: int         # Modbus address


# === AI device (DAM-3151+H, 32-ch analog input) ===
class AI(BaseDev):
    """
    DAM-3151+H:
      - 32 analog input channels
      - Channel n (0–31) value is in holding register 40001 + n
      - Each register is an unsigned 16-bit value, 0–65535, mapped to the configured range

    We just return the raw register value. Scaling to engineering units is done via plant.yaml (scale.gain/offset).
    """
    CH0_4X = 40001

    def read_channel(self, ch: int) -> Optional[int]:
        if ch < 0 or ch > 31:
            logger.warning(f"{self.name}: channel {ch} out of range for DAM-3151 (0–31)")
            return None
        off = reg4x_to_offset(self.CH0_4X) + ch  # 40001 → 0, so off = ch
        regs = self.bus.read_holding(self.unit, off, 1)
        return None if regs is None else regs[0]


# === TDA thermocouple device (DAM-3130D H or similar) ===
class TDA(BaseDev):
    # Simple assumption: channel 1 -> input reg 0, channel n -> n-1 (3x space)
    # (Good enough for now; we can refine from the TDA manual later.)
    def read_channel(self, ch: int) -> Optional[int]:
        if ch <= 0:
            logger.warning(f"{self.name}: channel index should start from 1 (got {ch})")
            return None
        off = max(0, ch - 1)
        regs = self.bus.read_input(self.unit, off, 1)
        return None if regs is None else regs[0]


# === AO analog output (0–10 V, fixed 3 decimals) ===
class AO(BaseDev):
    # CH1 at 0x000A, CHn = base + (n-1)
    CH1_4X = 0x000A

    def write_voltage_fixed3(self, ch: int, volts: float, reg_scale: int = 1000) -> bool:
        volts = max(0.0, min(10.0, float(volts)))
        raw = int(round(volts * reg_scale))
        if ch <= 0:
            logger.warning(f"{self.name}: AO channel index should start from 1 (got {ch})")
            return False
        address = self.CH1_4X + (ch - 1)
        return self.bus.write_holding(self.unit, address, raw)

    def write_percent_to_0_10v(self, ch: int, percent: float, reg_scale: int = 1000) -> bool:
        pct = max(0.0, min(100.0, float(percent)))
        volts = 10.0 * pct / 100.0
        return self.write_voltage_fixed3(ch, volts, reg_scale=reg_scale)


# === PPS: programmable power supply (percent command) ===
class PPS(BaseDev):
    CMD_4X = 0x0001

    def write_percent(self, percent: float) -> bool:
        pct = max(0.0, min(100.0, float(percent)))
        value = int(round(pct))
        return self.bus.write_holding(self.unit, self.CMD_4X, value)


# === Pump: speed command in percent ===
class Pump(BaseDev):
    CMD_4X = 0x0001

    def write_percent(self, percent: float) -> bool:
        pct = max(0.0, min(100.0, float(percent)))
        value = int(round(pct))
        return self.bus.write_holding(self.unit, self.CMD_4X, value)


# === Factory ===
def make_device(dev_name: str, dev_cfg: dict, bus) -> BaseDev:
    t = dev_cfg["type"].upper()
    unit = int(dev_cfg["addr"])
    if   t == "AI":   return AI(dev_name, bus, unit)
    elif t == "TDA":  return TDA(dev_name, bus, unit)
    elif t == "AO":   return AO(dev_name, bus, unit)
    elif t == "PPS":  return PPS(dev_name, bus, unit)
    elif t == "PUMP": return Pump(dev_name, bus, unit)
    else:
        raise ValueError(f"Unknown device type: {t}")
