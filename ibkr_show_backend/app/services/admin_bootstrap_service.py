from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    ).hex()


@dataclass
class AdminAuthData:
    initialized: bool = False
    username: str = ""
    password_hash: str = ""
    salt: str = ""
    session_secret: str = ""
    created_at: str = ""
    updated_at: str = ""


class AdminAuthStore:
    def __init__(self, config_file: str | Path) -> None:
        self.config_file = Path(config_file)

    def read(self) -> AdminAuthData:
        if not self.config_file.exists():
            return AdminAuthData()
        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                payload: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError):
            return AdminAuthData()
        return AdminAuthData(
            initialized=bool(payload.get("initialized")),
            username=str(payload.get("username") or ""),
            password_hash=str(payload.get("password_hash") or ""),
            salt=str(payload.get("salt") or ""),
            session_secret=str(payload.get("session_secret") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

    def save(self, data: AdminAuthData) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.config_file.name}.",
            suffix=".tmp",
            dir=self.config_file.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(data), f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.config_file)
            try:
                os.chmod(self.config_file, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class AdminAuthService:
    def __init__(
        self,
        settings: Settings,
        store: AdminAuthStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or AdminAuthStore(settings.admin_auth_config_file)

    def _data(self) -> AdminAuthData:
        return self.store.read()

    def is_initialized(self) -> bool:
        return self._data().initialized

    def get_effective_username(self) -> str:
        data = self._data()
        return data.username if data.initialized else self.settings.auth_username

    def verify_password(self, username: str, password: str) -> bool:
        data = self._data()
        if data.initialized:
            return (
                username == data.username
                and data.salt != ""
                and _hash_password(password, data.salt) == data.password_hash
            )
        return username == self.settings.auth_username and password == self.settings.auth_password

    def get_session_secret(self) -> str:
        data = self._data()
        if data.initialized and data.session_secret:
            return data.session_secret
        return self.settings.auth_session_secret

    def get_max_age_seconds(self) -> int:
        return self.settings.auth_session_max_age_seconds

    def bootstrap(self, username: str, password: str) -> AdminAuthData:
        if not username:
            raise ValueError("用户名不能为空")
        if len(password) < 8:
            raise ValueError("密码长度不能少于 8 位")

        data = self._data()
        if data.initialized:
            raise ValueError("系统已初始化，不能重复创建管理员账号")

        salt = secrets.token_hex(16)
        now = datetime.now(timezone.utc).isoformat()
        new_data = AdminAuthData(
            initialized=True,
            username=username,
            password_hash=_hash_password(password, salt),
            salt=salt,
            session_secret=secrets.token_urlsafe(48),
            created_at=now,
            updated_at=now,
        )
        self.store.save(new_data)
        return new_data

    def status(self) -> dict[str, Any]:
        data = self._data()
        return {
            "initialized": data.initialized,
            "auth_source": "file" if data.initialized else "env",
        }
