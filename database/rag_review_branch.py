#!/usr/bin/env python3
"""
Ревью текущей ветки по плану RAG: git diff → эмбеддинг запроса → top-k из SQLite → LLM.

Реализация: пакет database/rag_review_branch/ (main.py и модули).

Провайдер LLM: --llm gigachat|yandex или RAG_REVIEW_LLM (по умолчанию gigachat).
  GigaChat (Сбер): GIGACHAT_ACCESS_TOKEN, см. providers/gigachat_review_chat.py
  Yandex AI Studio: YANDEX_AI_STUDIO_API_KEY, YANDEX_FOLDER_ID, см. providers/yandex_review_chat.py

Нужно: make install-rag; для GigaChat — make gigachat-token → .temp_env.
TLS: GIGACHAT_SSL_VERIFY / YANDEX_SSL_VERIFY=0 или --insecure (оба флага для активного провайдера).

Кэш подготовки запроса (эмбеддинг + top-k + rag_section): .cache/rag_review_request; --no-request-cache.
Дебаг тела запроса к LLM: --debug-request или RAG_REVIEW_DEBUG_REQUEST=1 → .cache/rag_review_debug/last_llm_request.md

Git diff в модель: **`GIT_LOG_REF`** (или **`GIT_REVIEW_BRANCH`**) — правая сторона `git diff merge-base..REF` без checkout;
путь к клону: **`GIT_REVIEW_REPO`** или **`GITHUB_REPOSITORY`** + совпадение **`git remote origin`** (`repo_resolve`).

Примеры:
  python database/rag_review_branch.py --insecure --model GigaChat-2-Max -o review.md
  python database/rag_review_branch.py --llm yandex --model yandexgpt-5-pro/latest -o review.md
  python -m database.rag_review_branch --help
"""

from __future__ import annotations

import sys
from pathlib import Path

# Корень pr-review-rag (родитель каталога database/)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database.rag_review_branch.main import main

if __name__ == "__main__":
    raise SystemExit(main())
