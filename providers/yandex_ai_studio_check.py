#!/usr/bin/env python3
"""Проверка YANDEX_AI_STUDIO_API_KEY: короткий completion через AI Studio SDK.

Переменные (.env в корне репо или cwd):
  YANDEX_AI_STUDIO_API_KEY — секрет API-ключа
  YANDEX_FOLDER_ID или YC_FOLDER_ID — id каталога в Yandex Cloud

Опционально: YANDEX_COMPLETION_MODEL (по умолчанию yandexgpt).

Установка: pip install -r requirements-yandex.txt  (или make install-yandex)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "yandexgpt"
PROMPT = "Ответь одним словом: ок."


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    repo_root = _repo_root()
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(repo_root / ".env")

    api_key = os.environ.get("YANDEX_AI_STUDIO_API_KEY", "").strip()
    if not api_key:
        print(
            "error: set YANDEX_AI_STUDIO_API_KEY in .env",
            file=sys.stderr,
        )
        return 2

    folder_id = (
        os.environ.get("YANDEX_FOLDER_ID", "").strip()
        or os.environ.get("YC_FOLDER_ID", "").strip()
    )
    if not folder_id:
        print(
            "error: set YANDEX_FOLDER_ID (or YC_FOLDER_ID) — cloud folder id for AI Studio",
            file=sys.stderr,
        )
        return 2

    model_id = os.environ.get("YANDEX_COMPLETION_MODEL", "").strip() or DEFAULT_MODEL

    try:
        from yandex_ai_studio_sdk import AIStudio
    except ImportError:
        print(
            "error: pip install -r requirements-yandex.txt  (or: make install-yandex)",
            file=sys.stderr,
        )
        return 2

    print("Запрос к AI Studio (completion)...", flush=True)
    try:
        sdk = AIStudio(folder_id=folder_id, auth=api_key)
        model = sdk.models.completions(model_id)
        result = model.run(PROMPT)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    alts = getattr(result, "alternatives", None) or ()
    if not alts:
        print(f"error: empty response: {result!r}", file=sys.stderr)
        return 1

    text = getattr(alts[0], "text", None) or str(alts[0])
    preview = (text or "").strip().replace("\n", " ")[:200]
    print("ok: ключ и каталог приняты, модель ответила.")
    print(f"  model={model_id!r} preview: {preview!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
