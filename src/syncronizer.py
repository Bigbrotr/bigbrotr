import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from bigbrotr import Bigbrotr
from relay import Relay
from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector
import time
from utils import test_keypair
from multiprocessing import Pool, cpu_count
from relay_metadata import RelayMetadata
from compute_relay_metadata import compute_relay_metadata

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# --- Chunkify Function ---
def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# --- Config Loader ---
def load_config_from_env():
    try:
        config = {
            "dbhost": str(os.environ["POSTGRES_HOST"]),
            "dbuser": str(os.environ["POSTGRES_USER"]),
            "dbpass": str(os.environ["POSTGRES_PASSWORD"]),
            "dbname": str(os.environ["POSTGRES_DB"]),
            "dbport": int(os.environ["POSTGRES_PORT"]),
            "torhost": str(os.environ["TORPROXY_HOST"]),
            "torport": int(os.environ["TORPROXY_PORT"]),
            "num_cores": int(os.environ["SYNCRONIZER_NUM_CORES"]),
            "chunk_size": int(os.environ["SYNCRONIZER_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["SYNCRONIZER_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["SYNCRONIZER_REQUEST_TIMEOUT"]),
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["torport"] < 0 or config["torport"] > 65535:
            logging.error(
                "❌ Invalid TORPROXY_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["run_hour"] < 0 or config["run_hour"] > 23:
            logging.error(
                "❌ Invalid SYNCRONIZER_RUN_HOUR. Must be between 0 and 23.")
            sys.exit(1)
        if config["num_cores"] < 1:
            logging.error("❌ Invalid SYNCRONIZER_NUM_CORES. Must be at least 1.")
            sys.exit(1)
        if config["chunk_size"] < 1:
            logging.error("❌ Invalid SYNCRONIZER_CHUNK_SIZE. Must be at least 1.")
            sys.exit(1)
        if config["requests_per_core"] < 1:
            logging.error(
                "❌ Invalid SYNCRONIZER_REQUESTS_PER_CORE. Must be at least 1.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid SYNCRONIZER_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ SYNCRONIZER_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 SYNCRONIZER_NUM_CORES set to {config['num_cores']} (max available).")
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)
    return config


# --- Database Test ---
def test_database_connection(config):
    logging.info(
        f"🔌 Testing database connection to {config["dbhost"]}:{config["dbport"]}/{config["dbname"]}")
    try:
        db = Bigbrotr(config["dbhost"], config["dbport"],
                      config["dbuser"], config["dbpass"], config["dbname"])
        db.connect()
        logging.info("✅ Database connection successful.")
    except Exception as e:
        logging.exception("❌ Database connection failed.")
        raise
    finally:
        db.close()
        logging.info("🔌 Database connection closed.")


# --- Tor Proxy Test ---
async def test_torproxy_connection(config, timeout=10):
    socks5_proxy_url = f"socks5://{config["torhost"]}:{config["torport"]}"
    # HTTP Test
    http_url = "https://check.torproject.org"
    connector = ProxyConnector.from_url(socks5_proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor HTTP access...")
            async with session.get(http_url, timeout=timeout) as resp:
                text = await resp.text()
                if "Congratulations. This browser is configured to use Tor" in text:
                    logging.info("✅ HTTP response confirms Tor usage.")
                else:
                    raise RuntimeError("Tor usage not confirmed via HTTP.")
        except Exception:
            logging.exception("❌ HTTP test via Tor failed.")
            raise
        finally:
            await session.close()
            logging.info("🌐 HTTP connection closed.")
    # WebSocket Test
    ws_url = "wss://echo.websocket.events"
    connector = ProxyConnector.from_url(socks5_proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor WebSocket access...")
            async with session.ws_connect(ws_url, timeout=timeout) as ws:
                await ws.send_str("Hello via WebSocket")
                msg = await ws.receive(timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    logging.info(f"✅ WebSocket message received: {msg.data}")
                else:
                    raise RuntimeError(
                        f"Unexpected WebSocket response: {msg.type}")
        except Exception:
            logging.exception("❌ WebSocket test via Tor failed.")
            raise
        finally:
            await ws.close()
            logging.info("🌐 WebSocket connection closed.")


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        try:
            test_database_connection(config)
            await test_torproxy_connection(config)
            return
        except Exception as e:
            logging.warning(
                f"⏳ Service not ready (attempt {attempt}/{retries}): {e}")
    raise RuntimeError("❌ Required services not available after retries.")

















# --- Async Relay Processor ---
async def process_relay_events(relay, config, start_ts, end_ts):
    collected_events = []
    window = 60  # iniziale: 60 secondi
    current_start = start_ts
    max_ts_seen = start_ts

    while current_start < end_ts:
        current_end = min(current_start + window, end_ts)
        # simulate fetch via WSS (da implementare)
        events = await fetch_events_from_relay_wss(relay, current_start, current_end, config)

        if not events:
            current_start = current_end
            continue

        collected_events.extend(events)

        timestamps = [e["timestamp"] for e in events]
        max_ts = max(timestamps)

        # Heuristic: se ho eventi con timestamp > current_end, allora ho preso tutti gli eventi del range
        if max_ts > current_end:
            current_start = current_end
        else:
            # troppi eventi? probabilmente non abbiamo tutto -> riduco finestra
            if len(events) > relay.max_events_per_request:
                window = max(10, window // 2)
            else:
                window = min(3600, window * 2)
            current_start = max_ts + 1

    logging.info(f"Collected {len(collected_events)} events from {relay.url}")
    return collected_events

# --- Stub for WSS interaction ---
async def fetch_events_from_relay_wss(relay, start_ts, end_ts, config):
    await asyncio.sleep(0.05)  # simulate latency
    return [{"timestamp": ts, "data": f"event@{ts}"} for ts in range(start_ts, end_ts, 10)]

# --- Async Worker per Processo ---
async def process_chunk(chunk, config, start_ts, end_ts):
    sem = asyncio.Semaphore(config["requests_per_core"])
    all_events = []

    async def handle_relay(relay):
        async with sem:
            events = await process_relay_events(relay, config, start_ts, end_ts)
            return events

    tasks = [handle_relay(relay) for relay in chunk]
    results = await asyncio.gather(*tasks)

    for relay_events in results:
        all_events.extend(relay_events)

    return all_events

# --- Worker Sync Wrapper ---
def worker(chunk, config, start_ts, end_ts):
    async def run():
        return await process_chunk(chunk, config, start_ts, end_ts)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(run())

# --- Inserimento eventi nel DB (stub) ---
def insert_events_to_db(events, config):
    db = Bigbrotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
    db.connect()
    db.insert_events_batch(events)
    db.close()




















# --- Fetch Relay Metadata List from Database ---
def fetch_relay_metedata_list(bigbrotr):
    bigbrotr.connect()
    logging.info("🔌 Database connection established.")
    logging.info("📦 Fetching relay metadata from database...")
    query = "SELECT * FROM relay_metadata WHERE generated_at = (SELECT MAX(generated_at) FROM relay_metadata)"
    bigbrotr.execute(query)
    rows = bigbrotr.fetchall()
    bigbrotr.close()
    relay_metadata_list = []
    for row in rows:
        try:
            relay = Relay(row[0])
            relay_metadata = RelayMetadata(
                relay.url,
                **{
                    "generated_at": row[1],
                    "connection_success": row[2],
                    "nip11_success": row[3],
                    "openable": row[4],
                    "readable": row[5],
                    "writable": row[6],
                    "rtt_open": row[7],
                    "rtt_read": row[8],
                    "rtt_write": row[9],
                    "name": row[10],
                    "description": row[11],
                    "banner": row[12],
                    "icon": row[13],
                    "pubkey": row[14],
                    "contact": row[15],
                    "supported_nips": row[16],
                    "software": row[17],
                    "version": row[18],
                    "privacy_policy": row[19],
                    "terms_of_service": row[20],
                    "limitation": row[21],
                    "extra_fields": row[22]
                }
            )
            relay_metadata_list.append(relay_metadata)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid relay metadata: {row}. Error: {e}")
            continue
    logging.info(f"📦 {len(relay_metadata_list)} relay metadata fetched from database.")
    return relay_metadata_list


# --- Main Loop ---
async def main_loop(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    relay_metedata_list = fetch_relay_metedata_list(bigbrotr)
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relay_metedata_list, chunk_size))
    end_time = int(time.time())
    args = [(chunk, config, end_time) for chunk in chunks]
    logging.info(
        f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")
    with Pool(processes=num_cores) as pool:
        results = pool.starmap(worker, args)

# --- Syncronizer Entrypoint ---
async def syncronizer():
    config = load_config_from_env()
    logging.info("🔄 Starting Syncronizer...")
    await wait_for_services(config)
    while True:
        try:
            logging.info("🔄 Starting main loop...")
            await main_loop(config)
            logging.info("✅ Main loop completed successfully.")
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(syncronizer())
    except Exception:
        logging.exception("❌ Syncronizer failed to start.")
        sys.exit(1)
