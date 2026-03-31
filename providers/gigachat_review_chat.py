"""GigaChat (Сбер): chat/completions для RAG-ревью."""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import httpx

from providers.gigachat_oauth import _httpx_verify

DEFAULT_CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


def gigachat_chat_completions(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float,
    chat_url: str,
    token: str,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    mt = os.environ.get("GIGACHAT_MAX_TOKENS", "").strip()
    if mt.isdigit():
        payload["max_tokens"] = int(mt)
    rquid = os.environ.get("GIGACHAT_RQUID", "").strip() or str(uuid.uuid4())
    verify = _httpx_verify()
    try:
        with httpx.Client(timeout=120.0, verify=verify) as client:
            r = client.post(
                chat_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "RqUID": rquid,
                    "User-Agent": "pr-review-rag/1",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError as e:
        err = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err or "certificate verify failed" in err.lower():
            raise SystemExit(
                "error: TLS verify failed to GigaChat (corporate proxy / MITM).\n"
                "  Fix: add to repo .env  GIGACHAT_SSL_VERIFY=0  (see .env.example; dev only), or GIGACHAT_CA_BUNDLE=/path/to.pem\n"
                "  Or:  make rag-review-insecure  /  python database/rag_review_branch.py --insecure\n"
                "  (Обычный make rag-review не задаёт SSL-флаги — как и gigachat-token без -insecure.)"
            ) from e
        raise
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:800]
        print(f"error: HTTP {e.response.status_code}: {body}", file=sys.stderr)
        if e.response.status_code == 401:
            print(
                "hint: токен GigaChat истёк (~30 мин) или отозван. "
                "Обновите: make gigachat-token-insecure (из корня pr-review-rag, нужен SBER_AUTH_KEY в .env). "
                "Затем снова make rag-review-insecure. "
                "Если в .env лежит старый GIGACHAT_ACCESS_TOKEN — удалите его: свежий токен должен быть в .temp_env.",
                file=sys.stderr,
            )
        elif e.response.status_code == 403:
            print(
                "hint: 403 от прокси/WAF часто из‑за неверного пути. "
                "По умолчанию уже /api/v1/chat/completions. "
                "Обновите токен (make gigachat-token-insecure), проверьте scope. "
                "Старый URL /api/v2/chat/completions задавайте только если он у вас явно работает.",
                file=sys.stderr,
            )
        elif e.response.status_code == 404 and "model" in body.lower():
            print(
                "hint: неверный GIGACHAT_MODEL — id только из GET /api/v1/models. "
                "make gigachat-ping-insecure (в конце список type=chat). Пример: GigaChat-2, GigaChat-2-Pro.",
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
