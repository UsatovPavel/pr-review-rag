"""Yandex AI Studio: OpenAI-совместимый POST .../v1/chat/completions для RAG-ревью."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://llm.api.cloud.yandex.net/v1"
ALT_BASE_URL = "https://ai.api.cloud.yandex.net/v1"


def _yandex_httpx_verify() -> bool | str:
    flag = os.environ.get("YANDEX_SSL_VERIFY", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        print(
            "warning: YANDEX_SSL_VERIFY disabled TLS verification (dev only)",
            file=sys.stderr,
        )
        return False
    ca = (
        os.environ.get("YANDEX_CA_BUNDLE", "").strip()
        or os.environ.get("SSL_CERT_FILE", "").strip()
    )
    if ca and Path(ca).expanduser().is_file():
        return str(Path(ca).expanduser().resolve())
    return True


def yandex_folder_id() -> str:
    return (
        os.environ.get("YANDEX_FOLDER_ID", "").strip()
        or os.environ.get("YC_FOLDER_ID", "").strip()
    )


def resolve_yandex_model(model_cli: str | None, folder_id: str) -> str:
    """Полный id вида gpt://<folder>/...; короткое имя дополняется префиксом."""
    raw = (model_cli or os.environ.get("YANDEX_COMPLETION_MODEL", "").strip() or "yandexgpt/latest").strip()
    if raw.startswith("gpt://"):
        return raw
    return f"gpt://{folder_id}/{raw.lstrip('/')}"


def _yandex_auth_header(api_key: str) -> str:
    style = os.environ.get("YANDEX_OPENAI_AUTH", "").strip().lower()
    if style == "api_key":
        return f"Api-Key {api_key}"
    if style == "bearer":
        return f"Bearer {api_key}"
    # По умолчанию Bearer (как у типичного OpenAI SDK)
    return f"Bearer {api_key}"


def yandex_chat_completions(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float,
    api_key: str,
    folder_id: str,
) -> str:
    base = os.environ.get("YANDEX_OPENAI_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
    url = f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    mt = os.environ.get("YANDEX_MAX_TOKENS", "").strip()
    if mt.isdigit():
        payload["max_tokens"] = int(mt)

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": _yandex_auth_header(api_key),
        "x-folder-id": folder_id,
        "User-Agent": "pr-review-rag/1",
    }
    if os.environ.get("YANDEX_DATA_LOGGING", "").strip().lower() in ("0", "false", "no"):
        headers["x-data-logging-enabled"] = "false"

    verify = _yandex_httpx_verify()
    try:
        with httpx.Client(timeout=120.0, verify=verify) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError as e:
        err = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err or "certificate verify failed" in err.lower():
            raise SystemExit(
                "error: TLS verify failed to Yandex AI API.\n"
                "  Fix: YANDEX_SSL_VERIFY=0 (dev only) или YANDEX_CA_BUNDLE=/path/to.pem\n"
                "  Альтернативный хост: YANDEX_OPENAI_BASE_URL=" + ALT_BASE_URL
            ) from e
        raise
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:800]
        print(f"error: HTTP {e.response.status_code}: {body}", file=sys.stderr)
        if e.response.status_code == 401:
            print(
                "hint: Yandex — Failed to authenticate. Проверьте YANDEX_AI_STUDIO_API_KEY (секрет ключа), "
                "подгрузку .env (set -a; . ./.env), при необходимости YANDEX_OPENAI_AUTH=api_key вместо bearer.",
                file=sys.stderr,
            )
        elif e.response.status_code == 403:
            bl = body.lower()
            if "does not match" in bl and "folder" in bl:
                print(
                    "hint: YANDEX_FOLDER_ID (заголовок x-folder-id) должен быть **тем же каталогом**, "
                    "в котором создан API-ключ сервисного аккаунта. Иначе 403 permission_error.",
                    file=sys.stderr,
                )
                m = re.search(r"service account folder ID '([^']+)'", body, re.IGNORECASE)
                if m:
                    fid = m.group(1)
                    print(
                        f"  В ответе указан каталог ключа: задайте в .env YANDEX_FOLDER_ID={fid}",
                        file=sys.stderr,
                    )
            else:
                print(
                    "hint: 403 — права API-ключа на каталог, роли ai.*, или неверный YANDEX_FOLDER_ID.",
                    file=sys.stderr,
                )
        elif e.response.status_code == 404:
            print(
                "hint: проверьте URL: YANDEX_OPENAI_BASE_URL (по умолчанию "
                f"{DEFAULT_BASE_URL}) или попробуйте {ALT_BASE_URL}",
                file=sys.stderr,
            )
        raise SystemExit(1) from e

    choices = data.get("choices") or []
    if not choices:
        raise SystemExit(f"error: no choices in response: {data!r}")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not content:
        raise SystemExit(f"error: empty content: {data!r}")
    return str(content)
