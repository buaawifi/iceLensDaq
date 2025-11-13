
from time import sleep
from loguru import logger
from hal.hal import HAL

# Configure logging to both console and a file
logger.add("hal_smoke_test.log", level="INFO", rotation="1 MB", retention="10 days", compression="zip")
logger.info("Logging started")

def main():
    hal = HAL("config/plant.yaml")
    hal.start()
    try:
        for i in range(5):
            snap = hal.snapshot()
            for k in ("T_hot", "T_cold", "P_shell", "comm_bad"):
                if k in snap:
                    logger.info(f"{k} = {snap[k]['value']} ({snap[k]['quality']})")
            sleep(1.0)

        logger.info("Setting safe outputs to 0 (or min pump) ...")
        for tag in ("heater_cmd", "heater2_cmd", "valve_cmd"):
            hal.write(tag, 0.0)
        hal.write("pump_cmd", 20.0)  # keep a trickle by default; adjust to 0.0 if you prefer

        sleep(1.0)
        logger.info("Snapshot after writes:")
        logger.info(hal.snapshot())
    finally:
        hal.stop()

if __name__ == "__main__":
    main()
