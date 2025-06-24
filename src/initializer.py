import os
import sys
import time
import logging
from bigbrotr import Bigbrotr
from relay import Relay
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
            "seed_relays_path": str(os.environ["SEED_RELAYS_PATH"])
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT value. Must be between 0 and 65535.")
            sys.exit(1)
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)
    return config


# --- Insert Relays ---
def insert_relays(config):
    logging.info("🌐 Starting relay insertion process...")
    try:
        with open(config["seed_relays_path"], 'r') as f:
            lines = f.read().splitlines()
        relays = []
        for raw_url in lines:
            try:
                relay = Relay(raw_url)
                relays.append(relay)
            except (ValueError, TypeError) as e:
                logging.warning(
                    f"⚠️ Invalid relay URL skipped: {raw_url}. Reason: {e}")
        if relays:
            db = Bigbrotr(config["dbhost"], config["dbport"],
                          config["dbuser"], config["dbpass"], config["dbname"])
            db.connect()
            db.insert_relay_batch(relays, int(time.time()))
            logging.info(f"✅ Inserted {len(relays)} valid relays.")
            db.close()
        else:
            logging.warning("⚠️ No valid relays to insert.")
    except FileNotFoundError:
        logging.error(
            f"❌ Relay seed file not found: {config['seed_relays_path']}")
    except Exception as e:
        logging.exception(f"❌ Unexpected error during relay insertion: {e}")


# --- Retry Logic for Database ---
def wait_for_services(config, retries=5, delay=10):
    for attempt in range(1, retries + 1):
        time.sleep(delay)
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


# --- Main Entry Point ---
def initializer():
    config = load_config_from_env()
    wait_for_services(config)
    insert_relays(config)


# --- Monitor Entrypoint ---
if __name__ == "__main__":
    try:
        logging.info("🚀 Starting initializer...")
        initializer()
        logging.info("✅ Initializer completed successfully.")
    except Exception as e:
        logging.exception("❌ Initializer failed.")
        sys.exit(1)
