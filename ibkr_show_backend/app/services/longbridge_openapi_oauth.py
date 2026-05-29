from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.oauth_utils import mask_token

DEFAULT_OPENAPI_OAUTH_BASE_URL = "https://openapi.longbridge.com/oauth2"
TOKEN_REFRESH_SKEW_SECONDS = 300
PENDING_STATE_TTL_SECONDS = 900


class LongbridgeOpenAPIOAuthError(RuntimeError):
    """Raised when Longbridge OpenAPI OAuth cannot complete safely."""


@dataclass
class OpenAPIOAuthTokenSet:
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    scope: str = ""
    expires_at: int | None = None
    updated_at: int | None = None


@dataclass
class OpenAPIOAuthPendingState:
    state: str
    code_verifier: str
    redirect_uri: str
    scope: str
    created_at: int
    expires_at: int


@dataclass
class OpenAPIOAuthRegistration:
    client_id: str = ""
    client_id_issued_at: int | None = None
    registration_access_token: str = ""
    registration_client_uri: str = ""
    redirect_uris: list[str] = field(default_factory=list)


@dataclass
class LongbridgeOpenAPIOAuthState:
    issuer: str = DEFAULT_OPENAPI_OAUTH_BASE_URL
    client_id: str = ""
    token: OpenAPIOAuthTokenSet = field(default_factory=OpenAPIOAuthTokenSet)
    pending_states: dict[str, OpenAPIOAuthPendingState] = field(default_factory=dict)
    last_error: str = ""
    registration: OpenAPIOAuthRegistration | None = None


def _now() -> int:
    return int(time.time())


def _b64url_digest(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class LongbridgeOpenAPIOAuthStore:
    def __init__(self, config_file: str) -> None:
        self.config_file = Path(config_file).expanduser()

    def read(self) -> LongbridgeOpenAPIOAuthState:
        if not self.config_file.exists():
            return LongbridgeOpenAPIOAuthState()
        try:
            with self.config_file.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth config is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth config must be a JSON object")

        token_payload = payload.get("token") if isinstance(payload.get("token"), dict) else {}
        pending_payload = payload.get("pending_states") if isinstance(payload.get("pending_states"), dict) else {}
        pending_states: dict[str, OpenAPIOAuthPendingState] = {}
        for state, item in pending_payload.items():
            if not isinstance(item, dict):
                continue
            try:
                pending_states[str(state)] = OpenAPIOAuthPendingState(
                    state=str(item.get("state") or state),
                    code_verifier=str(item.get("code_verifier") or ""),
                    redirect_uri=str(item.get("redirect_uri") or ""),
                    scope=str(item.get("scope") or ""),
                    created_at=int(item.get("created_at") or 0),
                    expires_at=int(item.get("expires_at") or 0),
                )
            except (TypeError, ValueError):
                continue

        reg_payload = payload.get("registration") if isinstance(payload.get("registration"), dict) else None
        registration = None
        if reg_payload:
            registration = OpenAPIOAuthRegistration(
                client_id=str(reg_payload.get("client_id") or ""),
                client_id_issued_at=reg_payload.get("client_id_issued_at"),
                registration_access_token=str(reg_payload.get("registration_access_token") or ""),
                registration_client_uri=str(reg_payload.get("registration_client_uri") or ""),
                redirect_uris=list(reg_payload.get("redirect_uris") or []),
            )

        return LongbridgeOpenAPIOAuthState(
            issuer=str(payload.get("issuer") or DEFAULT_OPENAPI_OAUTH_BASE_URL),
            client_id=str(payload.get("client_id") or ""),
            token=OpenAPIOAuthTokenSet(
                access_token=str(token_payload.get("access_token") or ""),
                refresh_token=str(token_payload.get("refresh_token") or ""),
                token_type=str(token_payload.get("token_type") or "Bearer"),
                scope=str(token_payload.get("scope") or ""),
                expires_at=token_payload.get("expires_at"),
                updated_at=token_payload.get("updated_at"),
            ),
            pending_states=pending_states,
            last_error=str(payload.get("last_error") or ""),
            registration=registration,
        )

    def save(self, state: LongbridgeOpenAPIOAuthState) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.config_file.name}.", suffix=".tmp", dir=self.config_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.config_file)
            try:
                os.chmod(self.config_file, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def clear_token(self) -> LongbridgeOpenAPIOAuthState:
        state = self.read()
        state.token = OpenAPIOAuthTokenSet()
        state.pending_states = {}
        state.last_error = ""
        self.save(state)
        return state


class LongbridgeOpenAPIOAuthService:
    def __init__(
        self,
        settings: Settings | None = None,
        store: LongbridgeOpenAPIOAuthStore | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or LongbridgeOpenAPIOAuthStore(self.settings.longbridge_openapi_oauth_file)
        self._http_client = http_client

    def status(self) -> dict[str, Any]:
        state = self._read_and_prune()
        configured_client_id = self._client_id(state)
        token = state.token
        now = _now()
        expires_at = int(token.expires_at) if token.expires_at is not None else None
        connected = bool(configured_client_id and token.access_token and (expires_at is None or expires_at > now))
        return {
            "enabled": self.settings.longbridge_enable and connected,
            "configured": bool(configured_client_id),
            "oauth_connected": connected,
            "client_id_configured": bool(configured_client_id),
            "client_id": configured_client_id,
            "has_access_token": bool(token.access_token),
            "access_token_masked": mask_token(token.access_token),
            "has_refresh_token": bool(token.refresh_token),
            "refresh_token_masked": mask_token(token.refresh_token),
            "scope": token.scope or self.settings.longbridge_openapi_oauth_scope,
            "expires_at": expires_at,
            "expires_in_seconds": max(0, expires_at - now) if expires_at is not None else None,
            "auto_refresh_enabled": True,
            "refresh_available": bool(configured_client_id and token.refresh_token),
            "refresh_skew_seconds": TOKEN_REFRESH_SKEW_SECONDS,
            "pending_authorizations": len(state.pending_states),
            "last_error": state.last_error,
            "config_file": str(self.store.config_file),
            "sdk_token_cache_file": str(self._sdk_token_cache_path(configured_client_id)) if configured_client_id else "",
            "auto_registered": state.registration is not None and not self.settings.longbridge_openapi_oauth_client_id,
            "registration_client_uri": state.registration.registration_client_uri if state.registration else "",
            "message": "Longbridge OpenAPI OAuth is connected" if connected else "Longbridge OpenAPI OAuth is not connected",
        }

    def register_oauth_client(self, redirect_uri: str, scope: str | None = None) -> OpenAPIOAuthRegistration:
        payload = {
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "IBKR Show",
        }
        data = self._post_json(f"{DEFAULT_OPENAPI_OAUTH_BASE_URL}/register", payload)
        client_id = str(data.get("client_id") or "")
        if not client_id:
            raise LongbridgeOpenAPIOAuthError("Longbridge OAuth registration response is missing client_id")
        return OpenAPIOAuthRegistration(
            client_id=client_id,
            client_id_issued_at=data.get("client_id_issued_at"),
            registration_access_token=str(data.get("registration_access_token") or ""),
            registration_client_uri=str(data.get("registration_client_uri") or ""),
            redirect_uris=list(data.get("redirect_uris") or [redirect_uri]),
        )

    def start_authorization(self, redirect_uri: str, scope: str | None = None) -> dict[str, Any]:
        state = self._read_and_prune()
        client_id = self._client_id(state)
        if not client_id:
            registration = self.register_oauth_client(redirect_uri, scope)
            state.registration = registration
            state.client_id = registration.client_id
            self.store.save(state)
            client_id = registration.client_id
        normalized_scope = (scope if scope is not None else self.settings.longbridge_openapi_oauth_scope).strip()
        code_verifier = secrets.token_urlsafe(64)
        oauth_state = secrets.token_urlsafe(32)
        created_at = _now()
        pending = OpenAPIOAuthPendingState(
            state=oauth_state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            scope=normalized_scope,
            created_at=created_at,
            expires_at=created_at + PENDING_STATE_TTL_SECONDS,
        )
        state.client_id = client_id
        state.pending_states[oauth_state] = pending
        state.last_error = ""
        self.store.save(state)

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": oauth_state,
            "code_challenge": _b64url_digest(code_verifier),
            "code_challenge_method": "S256",
        }
        if normalized_scope:
            params["scope"] = normalized_scope
        return {
            "authorization_url": _append_query(f"{DEFAULT_OPENAPI_OAUTH_BASE_URL}/authorize", params),
            "state": oauth_state,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": normalized_scope,
            "expires_at": pending.expires_at,
        }

    def complete_authorization(self, code: str, state_value: str) -> dict[str, Any]:
        state = self._read_and_prune()
        pending = state.pending_states.get(state_value)
        if pending is None or pending.expires_at < _now():
            raise LongbridgeOpenAPIOAuthError("OAuth state is missing or expired")
        client_id = self._client_id(state)
        if not client_id:
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth client_id is not configured")
        token_data = self._post_form(
            f"{DEFAULT_OPENAPI_OAUTH_BASE_URL}/token",
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": pending.redirect_uri,
                "code": code,
                "code_verifier": pending.code_verifier,
            },
        )
        state.client_id = client_id
        state.token = self._token_from_response(token_data, requested_scope=pending.scope)
        state.pending_states.pop(state_value, None)
        state.last_error = ""
        self.store.save(state)
        self.sync_sdk_token_cache(state)
        return self.status()

    def refresh_token(self) -> dict[str, Any]:
        state = self.store.read()
        client_id = self._client_id(state)
        if not client_id:
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth client_id is not configured")
        if not state.token.refresh_token:
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth refresh token is missing")
        token_data = self._post_form(
            f"{DEFAULT_OPENAPI_OAUTH_BASE_URL}/token",
            {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": state.token.refresh_token},
        )
        previous_refresh_token = state.token.refresh_token
        state.client_id = client_id
        state.token = self._token_from_response(token_data, requested_scope=state.token.scope, fallback_refresh_token=previous_refresh_token)
        state.last_error = ""
        self.store.save(state)
        self.sync_sdk_token_cache(state)
        return asdict(state.token)

    def disconnect(self) -> dict[str, Any]:
        state = self.store.clear_token()
        client_id = self._client_id(state)
        if client_id:
            try:
                self._sdk_token_cache_path(client_id).unlink(missing_ok=True)
            except OSError:
                pass
        return {"connected": False, "message": "Longbridge OpenAPI OAuth token cleared"}

    def get_access_token(self) -> str | None:
        state = self._read_and_prune()
        token = state.token
        if not self._client_id(state) or not token.access_token:
            return None
        if token.expires_at is None:
            self.sync_sdk_token_cache(state)
            return token.access_token
        expires_at = int(token.expires_at)
        if expires_at - _now() > TOKEN_REFRESH_SKEW_SECONDS:
            self.sync_sdk_token_cache(state)
            return token.access_token
        if not token.refresh_token:
            return None if expires_at <= _now() else token.access_token
        try:
            refreshed = self.refresh_token()
            access_token = refreshed.get("access_token")
            return str(access_token) if access_token else None
        except Exception as exc:
            state.last_error = f"OpenAPI OAuth refresh failed: {str(exc)[:160]}"
            self.store.save(state)
            return None if expires_at <= _now() else token.access_token

    def sync_sdk_token_cache(self, state: LongbridgeOpenAPIOAuthState | None = None) -> None:
        state = state or self.store.read()
        client_id = self._client_id(state)
        token = state.token
        if not client_id or not token.access_token:
            return
        expires_at = int(token.expires_at) if token.expires_at is not None else 2**63 - 1
        payload = {
            "client_id": client_id,
            "access_token": token.access_token,
            "refresh_token": token.refresh_token or None,
            "expires_at": expires_at,
        }
        path = self._sdk_token_cache_path(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _client_id(self, state: LongbridgeOpenAPIOAuthState) -> str:
        return (
            self.settings.longbridge_openapi_oauth_client_id
            or state.client_id
            or (state.registration.client_id if state.registration else "")
            or ""
        ).strip()

    def _token_from_response(
        self,
        payload: dict[str, Any],
        *,
        requested_scope: str,
        fallback_refresh_token: str = "",
    ) -> OpenAPIOAuthTokenSet:
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth token response is missing access_token")
        expires_in = int(payload.get("expires_in") or 0)
        now = _now()
        return OpenAPIOAuthTokenSet(
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or fallback_refresh_token or ""),
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=str(payload.get("scope") or requested_scope),
            expires_at=now + expires_in if expires_in > 0 else None,
            updated_at=now,
        )

    def _post_form(self, endpoint: str, payload: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client().post(endpoint, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=httpx.Timeout(20))
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LongbridgeOpenAPIOAuthError(f"Longbridge OpenAPI OAuth token request failed: {str(exc)[:160]}") from exc
        if not isinstance(data, dict):
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth token response is not an object")
        if data.get("error"):
            raise LongbridgeOpenAPIOAuthError(str(data.get("error_description") or data.get("error")))
        return data

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client().post(endpoint, json=payload, timeout=httpx.Timeout(20))
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LongbridgeOpenAPIOAuthError(f"Longbridge OpenAPI OAuth request failed: {str(exc)[:160]}") from exc
        if not isinstance(data, dict):
            raise LongbridgeOpenAPIOAuthError("Longbridge OpenAPI OAuth response is not an object")
        if data.get("error"):
            raise LongbridgeOpenAPIOAuthError(str(data.get("error_description") or data.get("error")))
        return data

    def _read_and_prune(self) -> LongbridgeOpenAPIOAuthState:
        state = self.store.read()
        now = _now()
        state.pending_states = {
            key: item
            for key, item in state.pending_states.items()
            if item.expires_at > now and item.code_verifier and item.redirect_uri
        }
        return state

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client()
        return self._http_client

    def _sdk_token_cache_path(self, client_id: str) -> Path:
        return Path.home() / ".longbridge" / "openapi" / "tokens" / client_id


def _append_query(url: str, params: dict[str, str]) -> str:
    from urllib.parse import urlencode

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"
