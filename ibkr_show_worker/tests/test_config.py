from worker.core.config import get_settings


def test_flex_config_file_overrides_env_credentials(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "ibkr_flex.json"
    config_file.write_text('{"query_id": "json-query", "flex_token": "json-token"}', encoding="utf-8")
    monkeypatch.setenv("IBKR_FLEX_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("FLEX_QUERY_ID_DAILY", "env-query")
    monkeypatch.setenv("FLEX_TOKEN", "env-token")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.flex_query_id_daily == "json-query"
    assert settings.flex_token == "json-token"
    assert settings.flex_config_file == str(config_file)

    get_settings.cache_clear()


def test_flex_polling_defaults_wait_long_enough_for_slow_statement_generation(monkeypatch) -> None:
    monkeypatch.delenv("FLEX_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("FLEX_MAX_POLL_RETRIES", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.flex_poll_interval_seconds == 10
    assert settings.flex_max_poll_retries == 60
    assert settings.flex_poll_interval_seconds * settings.flex_max_poll_retries >= 600

    get_settings.cache_clear()
