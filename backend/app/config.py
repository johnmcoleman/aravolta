"""Central settings. Connection URLs are required and come from the environment
(or a local, gitignored .env file) — never hardcoded, so no credentials live in
source. See .env.example for the local-dev values that match docker-compose.yml."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env")

    # Infra connections — required, supplied via DATABASE_URL / CACHE_URL.
    # No defaults: keeps credentials out of source and fails fast if unset.
    database_url: str
    cache_url: str

    # Ingestion batching knobs — the heart of the "don't block on the DB" design.
    # The buffer flushes when EITHER condition trips, whichever comes first:
    batch_max_size: int = 500          # flush once this many rows are buffered
    batch_max_interval_ms: int = 250   # ...or this long has passed since last flush
    queue_max: int = 100_000           # backpressure ceiling: reject if buffer is this full
    # On a transient DB error, retry the batch this many times (exponential backoff)
    # before giving up. Covers the common case (a brief blip) without dropping data;
    # while retrying, the queue backs up and sheds load (503) rather than losing rows.
    flush_max_retries: int = 3

    # Fleet view: a device is "online" if its last reading is within this window.
    online_window_seconds: int = 30
    # Fleet-default alert limits — used ONLY when a device has no per-device limit
    # in the devices table. Per-device limits there are the source of truth.
    default_power_limit: float = 1000.0
    default_temp_limit: float = 85.0


settings = Settings()
