
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
        logger.info("Starting full channel test")

        # Iterate over all available points in the configuration
        for point in hal.config["points"]:
            try:
                # Get the point details
                snap = hal.snapshot()
                if point in snap:
                    value = snap[point]["value"]
                    quality = snap[point]["quality"]
                    # Log the point value and its quality status
                    logger.info(f"Point: {point} = {value} ({quality})")

                    # Test actuator commands (e.g., valves, pumps)
                    if "cmd" in point:
                        logger.info(f"Setting {point} to 0 for safety")
                        hal.write(point, 0.0)

            except Exception as e:
                logger.error(f"Error testing point {point}: {str(e)}")
            
            # Sleep between tests to avoid overloading
            sleep(1.0)

        # After testing all points, log the final snapshot
        logger.info("Final snapshot after testing all channels:")
        logger.info(hal.snapshot())

    finally:
        hal.stop()
        logger.info("HAL stopped after full channel test")

if __name__ == "__main__":
    main()
