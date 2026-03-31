#!/usr/bin/env python3
"""Проверка токена GigaChat: GET /api/v1/models (без генерации текста).

Загружает .env и .temp_env из корня репо. TLS: GIGACHAT_SSL_VERIFY, GIGACHAT_CA_BUNDLE.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx
from dotenv import load_dotenv

MODELS_URL = "https://gigachat.devices.sberbank.ru/api/v1/models"


def _root() -> Path:
    return _ROOT


def main() -> int:
    root = _root()
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(root / ".env")
    # Свежий токен из OAuth — в .temp_env; без override=True старый GIGACHAT_ACCESS_TOKEN из .env перекрывает его.
    load_dotenv(root / ".temp_env", override=True)
    load_dotenv(Path.cwd() / ".temp_env", override=True)

    from providers.gigachat_oauth import _httpx_verify

    token = os.environ.get("GIGACHAT_ACCESS_TOKEN", "").strip()
    if not token:
        print("error: no GIGACHAT_ACCESS_TOKEN — run: make gigachat-token-insecure", file=sys.stderr)
        return 2

    try:
        with httpx.Client(timeout=30.0, verify=_httpx_verify()) as c:
            r = c.get(
                MODELS_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
    except httpx.ConnectError as e:
        print(f"error: connect/TLS: {e}", file=sys.stderr)
        return 1

    print(f"HTTP {r.status_code}  {MODELS_URL}")
    ct = (r.headers.get("content-type") or "").lower()
    if "json" in ct:
        try:
            data = r.json()
            print(json.dumps(data, ensure_ascii=False, indent=2)[:8000])
            if len(json.dumps(data)) > 8000:
                print("\n... (truncated)")
        except json.JSONDecodeError:
            print(r.text[:2000])
    else:
        print(r.text[:2000])

    if r.status_code == 401:
        print("\nhint: токен недействителен или истёк (~30 мин) — make gigachat-token-insecure", file=sys.stderr)
    elif r.status_code == 403:
        print("\nhint: 403 — проверьте scope проекта, VPN, или попробуйте GIGACHAT_SSL_VERIFY=0 если MITM", file=sys.stderr)
    return 0 if r.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
