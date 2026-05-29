from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    flex_base_url: str
    flex_token: str
    flex_query_id_daily: str
    flex_user_agent: str
    flex_poll_interval_seconds: int
    flex_max_poll_retries: int
    es_host: str
    es_username: str
    es_password: str
    es_verify_certs: bool
    redis_url: str
    cache_key_prefix: str
    flex_config_file: str
    backend_base_url: str
    daily_review_internal_token: str


def _read_flex_config(config_file: str) -> dict:
    path = Path(config_file).expanduser()
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return {}

    return payload if isinstance(payload, dict) else {}


@lru_cache
def get_settings() -> Settings:
    flex_config_file = os.getenv(
        "IBKR_FLEX_CONFIG_FILE",
        str(BASE_DIR.parent / "ibkr_show_backend" / "data" / "config" / "ibkr_flex.json"),
    )
    flex_config = _read_flex_config(flex_config_file)
    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        flex_base_url=os.getenv(
            "FLEX_BASE_URL",
            "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService",
        ),
        flex_token=str(flex_config.get("flex_token") or os.getenv("FLEX_TOKEN", "")),
        flex_query_id_daily=str(flex_config.get("query_id") or os.getenv("FLEX_QUERY_ID_DAILY", "1419985")),
        flex_user_agent=os.getenv("FLEX_USER_AGENT", "ibkr-show-worker/0.1"),
        flex_poll_interval_seconds=int(os.getenv("FLEX_POLL_INTERVAL_SECONDS", "10")),
        flex_max_poll_retries=int(os.getenv("FLEX_MAX_POLL_RETRIES", "60")),
        es_host=os.getenv("ES_HOST", "http://localhost:9200"),
        es_username=os.getenv("ES_USERNAME", ""),
        es_password=os.getenv("ES_PASSWORD", ""),
        es_verify_certs=_read_bool("ES_VERIFY_CERTS", False),
        redis_url=os.getenv("REDIS_URL", ""),
        cache_key_prefix=os.getenv("CACHE_KEY_PREFIX", "ibkr-show"),
        flex_config_file=flex_config_file,
        backend_base_url=os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000"),
        daily_review_internal_token=os.getenv("DAILY_REVIEW_INTERNAL_TOKEN", ""),
    )
