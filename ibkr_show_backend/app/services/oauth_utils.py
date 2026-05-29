from __future__ import annotations


def mask_token(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return f"****{token[-4:]}"
