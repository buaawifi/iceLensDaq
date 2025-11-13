from time import sleep
from loguru import logger
from hal.hal import HAL

"""
Smoke test for the integrated HAL.

- Opens both control_bus and daq_bus.
- Prints snapshots of key tags every second.
- Reads raw registers from AI1001 (DAM-3151+H) for the channels defined in the IO table.
- Finally drives all actuators to a safe state (0 % / 0 V, low pump speed).
"""

AI_TAGS = ["T_env", "RH_env", "P_shell",
           "PV1001_fb", "DT1001",
           "CV1001_fb", "CV1002_fb", "CV1003_fb",
           "FT1001", "FT1002"]


def main():
    hal = HAL("config/plant.yaml")
    hal.start()
    try:
        for i in range(8):
            snap = hal.snapshot()
            logger.info(f"Snapshot #{i}")
            for tag in ["T_hot", "T_cold"] + AI_TAGS:
                tv = snap.get(tag)
                if tv is not None:
                    logger.info(f"  {tag}: value={tv['value']}, quality={tv['quality']}")
            sleep(1.0)

        # Direct raw read from AI1001 via driver
        ai = getattr(hal, "devices", {}).get("AI1001")
        if ai is not None:
            logger.info("Reading raw channels from AI1001 via driver ...")
            for ch in [16, 17, 18, 19, 24, 25, 26, 28, 29, 30]:
                raw = ai.read_channel(ch)
                logger.info(f"  AI1001 CH{ch:02d}: raw={raw}")
        else:
            logger.warning("AI1001 not found in hal.devices")

        logger.info("Setting safe outputs to 0 (or min pump) ...")
        for tag in ("heater_cmd", "heater2_cmd", "valve_cmd"):
            hal.write(tag, 0.0)
        hal.write("pump_cmd", 20.0)  # keep a trickle by default; set 0.0 if you prefer

        sleep(1.0)
        logger.info("Snapshot after writes:")
        logger.info(hal.snapshot())
    finally:
        hal.stop()


if __name__ == "__main__":
    main()
