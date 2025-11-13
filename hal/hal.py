from __future__ import annotations
import threading, queue, time
from dataclasses import dataclass
from typing import Dict, Any
from loguru import logger

from hal.config import PlantConfig
from hal.modbus_bus import ModbusBus, BusSpec
from hal.drivers import make_device, AO, AI, TDA, PPS, Pump

@dataclass
class TagValue:
    """
    Represents a tag value with associated metadata.

    Attributes:
        value (float | None): The value of the tag (e.g., sensor reading or actuator setpoint).
        ts (float): The timestamp of the value in seconds (since epoch).
        quality (str): The quality of the data ("Good", "Bad", "Unknown").
    """
    value: float | None
    ts: float
    quality: str  # "Good"/"Bad"/"Unknown"

class HAL:
    """
    The Hardware Abstraction Layer (HAL) that manages communication with devices via Modbus.

    This class handles the initialization of buses, device connections, and provides methods
    to acquire data and dispatch control commands to the devices.

    Attributes:
        cfg (PlantConfig): The configuration object that holds plant setup (ports, devices, points).
        buses (dict[str, ModbusBus]): A dictionary of Modbus buses keyed by bus name.
        devices (dict): A dictionary of devices created from the configuration.
        tags (dict): A mapping of tag names to device channels.
        data (dict): A live data store for storing the current values, timestamps, and quality of tags.
        data_lock (threading.Lock): A lock for thread-safe access to `data`.
        write_q (queue.Queue): A queue for holding write commands to be processed by the control loop.
        _stop (threading.Event): An event used to signal the stopping of threads.
        t_daq (threading.Thread): The data acquisition thread.
        t_ctl (threading.Thread): The control loop thread.
    """
    
    def __init__(self, plant_path="config/plant.yaml"):
        """
        Initializes the HAL object, loads configuration, and sets up Modbus buses and devices.

        Args:
            plant_path (str): Path to the plant configuration YAML file (default is "config/plant.yaml").
        """
        self.cfg = PlantConfig(plant_path)

        # Build buses from configuration
        self.buses: dict[str, ModbusBus] = {}
        for bus_name, p in self.cfg.ports.items():
            spec = BusSpec(
                port=p["port"], baud=p.get("baud",9600), parity=p.get("parity","N"),
                stopbits=p.get("stopbits",1), bytesize=p.get("bytesize",8),
                timeout_ms=p.get("timeout_ms", p.get("timeout",200))
            )
            self.buses[bus_name] = ModbusBus(bus_name, spec)

        # Attach devices to their buses
        self.devices = {}
        for name, d in self.cfg.devices.items():
            bus = self.buses[d["bus"]]
            self.devices[name] = make_device(name, d, bus)

        # Mapping tag -> (device_name, point_cfg)
        self.tags = self.cfg.points

        # Live data store for tags
        self.data: Dict[str, TagValue] = {}
        self.data_lock = threading.Lock()

        # Writer queue (tag, value) for control commands
        self.write_q: queue.Queue[tuple[str, float]] = queue.Queue()

        # Threads for data acquisition and control
        self._stop = threading.Event()
        self.t_daq = threading.Thread(target=self._daq_loop, name="HAL-DAQ", daemon=True)
        self.t_ctl = threading.Thread(target=self._ctl_loop, name="HAL-CTL", daemon=True)

    # --- lifecycle ---    
    def start(self):
        """
        Starts the HAL system, opening Modbus buses and starting the data acquisition and control threads.
        """
        for b in self.buses.values():
            b.open()
        self.t_daq.start()
        self.t_ctl.start()
        logger.info("HAL started.")

    def stop(self):
        """
        Stops the HAL system, closing Modbus buses and stopping the threads.
        """
        self._stop.set()
        self.t_daq.join(timeout=1.0)
        self.t_ctl.join(timeout=1.0)
        for b in self.buses.values():
            b.close()
        logger.info("HAL stopped.")

    # --- public API ---    
    def snapshot(self) -> dict[str, dict]:
        """
        Returns a snapshot of the current data for all tags.

        Returns:
            dict: A dictionary containing the current value, timestamp, and quality of each tag.
        """
        with self.data_lock:
            return {k: {"value": v.value, "ts": v.ts, "quality": v.quality} for k, v in self.data.items()}

    def write(self, tag: str, value: float):
        """
        Queues a write command for a specific tag.

        Args:
            tag (str): The tag to write to (e.g., "T_hot", "P_shell").
            value (float): The value to write to the tag.
        """
        self.write_q.put((tag, float(value)))

    # --- internals ---    
    def _set_tag(self, tag: str, value: float | None, q: str):
        """
        Sets the value, timestamp, and quality for a tag in the live data store.

        Args:
            tag (str): The tag to update.
            value (float | None): The value to set, or None if the value is unavailable.
            q (str): The quality of the data ("Good", "Bad", "Unknown").
        """
        with self.data_lock:
            self.data[tag] = TagValue(value=value, ts=time.time(), quality=q)

    def _daq_loop(self):
        """
        The data acquisition loop. Periodically reads data from AI/TDA devices and updates the tag values.
        """
        period = 0.2  # seconds
        while not self._stop.is_set():
            any_bad = False
            for tag, p in self.tags.items():
                dev_name = p.get("device")
                if not dev_name:
                    continue
                dev = self.devices[dev_name]
                try:
                    if isinstance(dev, (AI, TDA)):
                        ch = int(p.get("channel", 0))
                        raw = dev.read_channel(ch)
                        if raw is None:
                            self._set_tag(tag, None, "Bad"); any_bad = True; continue
                        # Optional linear scale
                        scale = p.get("scale", {})
                        gain = scale.get("gain", 1.0) if isinstance(scale, dict) else float(scale or 1.0)
                        offset = scale.get("offset", 0.0) if isinstance(scale, dict) else 0.0
                        val = raw * gain + offset
                        self._set_tag(tag, val, "Good")
                    else:
                        # Actuator tag; skip in DAQ loop
                        continue
                except Exception as e:
                    any_bad = True
                    self._set_tag(tag, None, "Bad")
                    logger.debug(f"DAQ error @ {tag}: {e}")

            # update computed comm_bad if present
            if "comm_bad" in self.tags:
                self._set_tag("comm_bad", 1.0 if any_bad else 0.0, "Good")

            time.sleep(period)

    def _ctl_loop(self):
        """
        The control loop. Consumes write commands from the queue and dispatches them to the appropriate devices.
        """
        while not self._stop.is_set():
            try:
                tag, value = self.write_q.get(timeout=0.1)
            except queue.Empty:
                continue

            p = self.tags.get(tag, {})
            dev_name = p.get("device")
            if not dev_name:
                logger.warning(f"Write to logic/unknown tag '{tag}' ignored.")
                continue
            dev = self.devices[dev_name]
            try:
                ok = False
                # Dispatch based on device type
                if isinstance(dev, AO):
                    ch = int(p.get("channel", 1))
                    reg_scale = int(p.get("reg_scale", 1000))
                    # Interpret value as percent unless caller supplies volts explicitly via 'unit' == "V" and 'raw' field
                    unit = p.get("unit", "").upper()
                    if unit == "V" and p.get("kind","").lower() != "percent":
                        ok = dev.write_voltage_fixed3(ch, float(value), reg_scale)
                    else:
                        ok = dev.write_percent_to_0_10v(ch, float(value), reg_scale)
                elif isinstance(dev, (PPS, Pump)):
                    ok = dev.write_percent(float(value))
                else:
                    logger.warning(f"Tag '{tag}' maps to non-writable device type.")
                    ok = False

                self._set_tag(tag, float(value) if ok else None, "Good" if ok else "Bad")
                if not ok:
                    logger.warning(f"Write failed: {tag} -> {value}")
            except Exception as e:
                self._set_tag(tag, None, "Bad")
                logger.debug(f"Write error @ {tag}: {e}")
