import os
import sys
import asyncio
import logging
from functions import test_database_connection


# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


# --- Config Loader ---
def load_config_from_env():
    try:
        config = {
            "dbhost": str(os.environ["POSTGRES_HOST"]),
            "dbuser": str(os.environ["POSTGRES_USER"]),
            "dbpass": str(os.environ["POSTGRES_PASSWORD"]),
            "dbname": str(os.environ["POSTGRES_DB"]),
            "dbport": int(os.environ["POSTGRES_PORT"]),
            "frequency_hour": int(os.environ["FINDER_FREQUENCY_HOUR"]),
            "timeout": int(os.environ["FINDER_REQUEST_TIMEOUT"]),
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["frequency_hour"] < 1:
            logging.error(
                "❌ Invalid FINDER_FREQUENCY_HOUR. Must be at least 1.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid FINDER_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)
    return config


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        database_connection = test_database_connection(
            config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
        if database_connection:
            logging.info("✅ All required services are available.")
            return
        else:
            logging.warning(
                f"⚠️ Attempt {attempt}/{retries} failed. Retrying in {delay} seconds...")
    raise RuntimeError(
        "❌ Required services are not available after multiple attempts. Exiting.")


# --- Finder Entrypoint ---
async def finder():
    config = load_config_from_env()
    logging.info("🔍 Starting finder...")
    await wait_for_services(config)
    while True:
        try:
            # TODO: Implement the main finder logic here
            pass
        except Exception as e:
            logging.exception(f"❌ Finder encountered an error: {e}")
        await asyncio.sleep(config["frequency_hour"] * 3600)


if __name__ == "__main__":
    try:
        asyncio.run(finder())
    except Exception:
        logging.exception("❌ Finder failed to start.")
        sys.exit(1)
