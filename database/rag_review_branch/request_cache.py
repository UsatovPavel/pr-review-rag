"""Кэш подготовки RAG-запроса (rag_section + k), не ответа LLM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .constants import QUERY_TEXT_PREFIX, REQUEST_CACHE_SCHEMA


def _request_cache_key(
    diff_for_model: str,
    embed_model: str,
    db_fp: str,
    k: int,
) -> str:
    diff_h = hashlib.sha256(diff_for_model.encode("utf-8")).hexdigest()
    blob = json.dumps(
        {
            "schema": REQUEST_CACHE_SCHEMA,
            "diff_sha256": diff_h,
            "embed_model": embed_model,
            "db": db_fp,
            "k": k,
            "prefix": QUERY_TEXT_PREFIX,
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _try_load_request_cache(cache_file: Path) -> tuple[str, int] | None:
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("v") != 1:
        return None
    rs = data.get("rag_section")
    if not isinstance(rs, str):
        return None
    ku = data.get("k_used")
    k_used = int(ku) if isinstance(ku, int) and ku > 0 else -1
    return (rs, k_used)


def _save_request_cache(cache_file: Path, rag_section: str, k_used: int) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"v": 1, "rag_section": rag_section, "k_used": k_used}
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
