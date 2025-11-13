# config.py

"""
This module is responsible for loading and managing the plant configuration from a YAML file.
It provides an abstraction layer for accessing various configuration parameters related to the 
hardware setup, including RS-485 ports, devices, sensors, and logical conditions for the system.

The configuration data is read from a `plant.yaml` file and parsed into Python dictionaries. The 
primary function of this module is to map the configuration data to software-accessible attributes, 
allowing the system to interact with hardware components in a modular and flexible manner.

Key Features:
1. Loads YAML configuration files for hardware and system parameters.
2. Provides easy access to bus parameters, devices, points (tags), and logical conditions.
3. Allows querying of specific hardware configurations, such as ports and devices connected to each bus.
4. Supports mapping of physical devices and sensors to software tags, enabling a dynamic control system.
5. Defines interlock logic and safety conditions to ensure system stability and safe operation.

Usage:
- `load_yaml`: A function to load and parse YAML files into Python dictionaries.
- `PlantConfig`: A class for handling the configuration of ports, devices, and points.
  - `get_bus_params`: Retrieve the parameters of a specified bus.
  - `iter_devices_on_bus`: Iterate over all devices connected to a specific bus.
  - `point`: Retrieve the configuration details of a specific tag (sensor or actuator).
  - `device`: Retrieve the configuration details of a specific device (e.g., pumps, heaters).
"""

from ruamel.yaml import YAML
from pathlib import Path

# Initialize YAML parser for safe loading of YAML content
yaml = YAML(typ="safe")

def load_yaml(path: str | Path) -> dict:
    """
    Loads a YAML file and returns its content as a Python dictionary.

    Args:
        path (str | Path): The path to the YAML file to be loaded.

    Returns:
        dict: The parsed content of the YAML file.

    Raises:
        FileNotFoundError: If the file does not exist at the provided path.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return yaml.load(p.read_text(encoding="utf-8"))

class PlantConfig:
    """
    A class that handles the loading and accessing of plant configuration from a YAML file.

    Attributes:
        ports (dict): A dictionary containing port configurations (e.g., RS-485 settings).
        devices (dict): A dictionary containing the devices' configurations (e.g., pumps, heaters).
        points (dict): A dictionary mapping each tag to a specific device or sensor channel.
        logic (dict): A dictionary defining logical conditions and interlocks.

    Methods:
        get_bus_params(bus_name: str) -> dict:
            Returns the parameters of the specified bus (e.g., COM port settings).
        iter_devices_on_bus(bus_name: str):
            Iterates through devices connected to a specific bus.
        point(tag: str) -> dict:
            Retrieves the configuration details for a specific tag (e.g., temperature sensor).
        device(dev_name: str) -> dict:
            Retrieves the configuration details for a specific device (e.g., pump, heater).
    """
    
    def __init__(self, plant_path="config/plant.yaml"):
        """
        Initializes the PlantConfig class and loads the YAML configuration file.

        Args:
            plant_path (str): Path to the plant configuration YAML file (default is "config/plant.yaml").
        """
        self._raw = load_yaml(plant_path)
        self.ports: dict = self._raw.get("ports", {})  # Port configurations (e.g., RS-485 buses)
        self.devices: dict = self._raw.get("devices", {})  # Devices configuration (e.g., pumps, sensors)
        self.points: dict  = self._raw.get("points", {})  # Mapped points (e.g., sensors, outputs)
        self.logic: dict   = self._raw.get("logic", {})   # Logical conditions and interlocks

    def get_bus_params(self, bus_name: str) -> dict:
        """
        Retrieves the parameters for a specific bus.

        Args:
            bus_name (str): The name of the bus (e.g., "control_bus", "daq_bus").

        Returns:
            dict: The configuration details for the specified bus.
        """
        return self.ports[bus_name]

    def iter_devices_on_bus(self, bus_name: str):
        """
        Iterates over all devices connected to a specific bus.

        Args:
            bus_name (str): The name of the bus to iterate over (e.g., "control_bus").

        Yields:
            tuple: A tuple containing the device name and its configuration details.
        """
        for name, d in self.devices.items():
            if d.get("bus") == bus_name:
                yield name, d

    def point(self, tag: str) -> dict:
        """
        Retrieves the configuration details for a specific tag.

        Args:
            tag (str): The tag name to retrieve (e.g., "T_hot", "P_shell").

        Returns:
            dict: The configuration details associated with the specified tag.
        """
        return self.points[tag]

    def device(self, dev_name: str) -> dict:
        """
        Retrieves the configuration details for a specific device.

        Args:
            dev_name (str): The device name (e.g., "PPS1001", "Pump1001").

        Returns:
            dict: The configuration details for the specified device.
        """
        return self.devices[dev_name]
