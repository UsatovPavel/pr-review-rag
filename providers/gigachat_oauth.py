#!/usr/bin/env python3
"""POST /api/v2/oauth → write GIGACHAT_ACCESS_TOKEN to .temp_env (see GigaChatGuide.md).

TLS: if you see CERTIFICATE_VERIFY_FAILED (corporate proxy / missing CA), either set
`GIGACHAT_CA_BUNDLE` / `SSL_CERT_FILE` to a PEM bundle, or for local dev only
`GIGACHAT_SSL_VERIFY=0` (disables verification — insecure).
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_SCOPE = "GIGACHAT_API_PERS"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _httpx_verify() -> bool | str:
    flag = os.environ.get("GIGACHAT_SSL_VERIFY", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        print(
            "warning: GIGACHAT_SSL_VERIFY disabled TLS verification (dev only)",
            file=sys.stderr,
        )
        return False
    ca = (
        os.environ.get("GIGACHAT_CA_BUNDLE", "").strip()
        or os.environ.get("SSL_CERT_FILE", "").strip()
    )
    if ca and Path(ca).expanduser().is_file():
        return str(Path(ca).expanduser().resolve())
    return True


def _basic_header(raw: str) -> str:
    k = raw.strip()
    if k.lower().startswith("basic "):
        return k
    return f"Basic {k}"


def main() -> int:
    repo_root = _repo_root()
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(repo_root / ".env")

    key = os.environ.get("SBER_AUTH_KEY", "").strip()
    if not key:
        print("error: set SBER_AUTH_KEY (Authorization key for Basic header)", file=sys.stderr)
        return 2

    scope = os.environ.get("GIGACHAT_SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
    rquid = str(uuid.uuid4())

    try:
        with httpx.Client(timeout=60.0, verify=_httpx_verify()) as client:
            r = client.post(
                OAUTH_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": rquid,
                    "Authorization": _basic_header(key),
                },
                data={"scope": scope},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        print(f"error: HTTP {e.response.status_code}: {e.response.text[:500]}", file=sys.stderr)
        return 1
    except httpx.RequestError as e:
        print(f"error: request failed: {e}", file=sys.stderr)
        return 1

    token = data.get("access_token")
    if not token:
        print(f"error: no access_token in response: {data!r}", file=sys.stderr)
        return 1

    out = repo_root / ".temp_env"
    lines = [f"GIGACHAT_ACCESS_TOKEN={token}"]
    if "expires_at" in data:
        lines.append(f"GIGACHAT_TOKEN_EXPIRES_AT={data['expires_at']}")
    elif "expires_in" in data:
        lines.append(f"GIGACHAT_TOKEN_EXPIRES_IN={data['expires_in']}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
