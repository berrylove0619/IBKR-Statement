from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.admin_ibkr import (
    IBKRFlexSettingsResponse,
    IBKRFlexSettingsUpdateRequest,
    IBKRFlexTestResponse,
    IBKRImportResponse,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
WORKER_DIR = REPO_DIR / "ibkr_show_worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from worker.clients.es_client import ElasticsearchWriter  # noqa: E402
from worker.core.config import Settings as WorkerSettings  # noqa: E402
from worker.jobs.import_daily_snapshot import import_daily_snapshot_file  # noqa: E402

MASKED_TOKEN_MARKER = "****"


class AdminIBKRError(ValueError):
    """Raised when IBKR admin operations cannot be completed."""


@dataclass
class IBKRFlexConfig:
    query_id: str = ""
    flex_token: str = ""


def mask_flex_token(token: str | None) -> str:
    if not token:
        return ""

    value = token.strip()
    if len(value) <= 8:
        return MASKED_TOKEN_MARKER

    return f"{MASKED_TOKEN_MARKER}{value[-4:]}"


class IBKRFlexConfigStore:
    def __init__(self, config_file: str) -> None:
        self.config_file = Path(config_file).expanduser()

    def read(self) -> IBKRFlexConfig:
        if not self.config_file.exists():
            return IBKRFlexConfig()

        try:
            with self.config_file.open("r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
        except json.JSONDecodeError as exc:
            raise AdminIBKRError("IBKR 配置文件不是合法 JSON") from exc

        if not isinstance(payload, dict):
            raise AdminIBKRError("IBKR 配置文件必须是 JSON object")

        return IBKRFlexConfig(
            query_id=str(payload.get("query_id") or payload.get("flex_query_id_daily") or ""),
            flex_token=str(payload.get("flex_token") or ""),
        )

    def save(self, config: IBKRFlexConfig) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.config_file.name}.",
            suffix=".tmp",
            dir=self.config_file.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(asdict(config), temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
            os.replace(temp_path, self.config_file)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class AdminIBKRService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = IBKRFlexConfigStore(settings.ibkr_flex_config_file)

    def get_settings(self) -> IBKRFlexSettingsResponse:
        config = self._effective_config()
        return self._to_public_settings(config)

    def update_settings(self, payload: IBKRFlexSettingsUpdateRequest) -> IBKRFlexSettingsResponse:
        current = self._effective_config()
        query_id = current.query_id
        flex_token = current.flex_token

        if payload.query_id is not None:
            query_id = payload.query_id.strip()
        if payload.flex_token is not None and payload.flex_token.strip():
            flex_token = payload.flex_token.strip()

        if not query_id:
            raise AdminIBKRError("Query ID 不能为空")

        config = IBKRFlexConfig(query_id=query_id, flex_token=flex_token)
        self.store.save(config)
        return self._to_public_settings(config)

    def test_connection(self) -> IBKRFlexTestResponse:
        config = self._require_config()
        worker_settings = self._worker_settings(config)
        FlexClient, FlexClientError = _load_flex_client()
        try:
            reference_code = FlexClient(worker_settings).send_request(config.query_id)
        except FlexClientError as exc:
            return IBKRFlexTestResponse(success=False, query_id=config.query_id, message=str(exc))

        return IBKRFlexTestResponse(
            success=True,
            query_id=config.query_id,
            reference_code=reference_code,
            message="IBKR Flex 请求已提交成功",
        )

    def pull_daily_from_ibkr(self) -> IBKRImportResponse:
        config = self._require_config()
        worker_settings = self._worker_settings(config)
        FlexClient, FlexClientError = _load_flex_client()
        with tempfile.NamedTemporaryFile(prefix="ibkr_daily_", suffix=".csv", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            downloaded_file = FlexClient(worker_settings).download_flex_statement(config.query_id, temp_path)
            result = self._import_file(downloaded_file, worker_settings)
            return IBKRImportResponse(
                success=True,
                filename=downloaded_file.name,
                result=result,
                message="已从 IBKR 拉取并导入数据",
            )
        except FlexClientError as exc:
            raise AdminIBKRError(str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

    def import_history_csv(self, filename: str, content: bytes) -> IBKRImportResponse:
        if not content:
            raise AdminIBKRError("上传文件为空")

        config = self._effective_config()
        worker_settings = self._worker_settings(config)
        safe_suffix = ".csv"
        if filename.lower().endswith(".txt"):
            safe_suffix = ".txt"

        with tempfile.NamedTemporaryFile(prefix="ibkr_history_", suffix=safe_suffix, delete=False) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        try:
            result = self._import_file(temp_path, worker_settings)
            return IBKRImportResponse(
                success=True,
                filename=filename or temp_path.name,
                result=result,
                message="历史数据已导入",
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def _import_file(self, file_path: Path, worker_settings: WorkerSettings) -> dict[str, Any]:
        try:
            return import_daily_snapshot_file(
                ElasticsearchWriter(worker_settings),
                file_path,
                settings=worker_settings,
            )
        except Exception as exc:
            raise AdminIBKRError(f"IBKR 数据导入失败：{exc}") from exc

    def _effective_config(self) -> IBKRFlexConfig:
        config = self.store.read()
        return IBKRFlexConfig(
            query_id=config.query_id or os.getenv("FLEX_QUERY_ID_DAILY", "1419985"),
            flex_token=config.flex_token or os.getenv("FLEX_TOKEN", ""),
        )

    def _require_config(self) -> IBKRFlexConfig:
        config = self._effective_config()
        if not config.query_id:
            raise AdminIBKRError("请先填写 IBKR Query ID")
        if not config.flex_token:
            raise AdminIBKRError("请先填写 IBKR FLEX_TOKEN")
        return config

    def _to_public_settings(self, config: IBKRFlexConfig) -> IBKRFlexSettingsResponse:
        return IBKRFlexSettingsResponse(
            query_id=config.query_id,
            flex_token_masked=mask_flex_token(config.flex_token),
            has_flex_token=bool(config.flex_token),
            config_file=str(self.store.config_file),
        )

    def _worker_settings(self, config: IBKRFlexConfig) -> WorkerSettings:
        return WorkerSettings(
            app_env=self.settings.app_env,
            flex_base_url=self.settings.ibkr_flex_base_url,
            flex_token=config.flex_token,
            flex_query_id_daily=config.query_id,
            flex_user_agent=self.settings.ibkr_flex_user_agent,
            flex_poll_interval_seconds=self.settings.ibkr_flex_poll_interval_seconds,
            flex_max_poll_retries=self.settings.ibkr_flex_max_poll_retries,
            es_host=self.settings.es_host,
            es_username=self.settings.es_username,
            es_password=self.settings.es_password,
            es_verify_certs=self.settings.es_verify_certs,
            redis_url=self.settings.redis_url,
            cache_key_prefix=self.settings.cache_key_prefix,
            flex_config_file=self.settings.ibkr_flex_config_file,
            backend_base_url=f"http://{self.settings.app_host if self.settings.app_host != '0.0.0.0' else '127.0.0.1'}:{self.settings.app_port}",
            daily_review_internal_token=self.settings.daily_review_internal_token,
        )


def _load_flex_client():
    from worker.clients.flex_client import FlexClient, FlexClientError

    return FlexClient, FlexClientError
