#!/usr/bin/env python3
"""Импорт PR-комментариев в SQLite (см. RAG по экспортированным коммам.md).

Таблица chunks: id, source, text, meta (JSON), embedding (BLOB float32, опционально).

По умолчанию: export/pr_comments.jsonl → review_rag.sqlite
Если есть export/rag_embed/embeddings.npy и число строк совпадает — пишутся векторы.

Зависимости: stdlib + numpy только при --embeddings (или make install-rag).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable


def _row_to_text_loader() -> Callable[[dict[str, Any]], str]:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "providers" / "local_rag_embeddings.py"
    spec = importlib.util.spec_from_file_location("_local_rag_embeddings", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.row_to_text  # type: ignore[attr-defined]


def _source_from_obj(obj: dict[str, Any]) -> str:
    url = obj.get("html_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    pr = obj.get("pr")
    return f"PR #{pr}" if pr is not None else ""


def _iter_comments(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _load_embeddings_npy(path: Path) -> Any:
    try:
        import numpy as np
    except ImportError as e:
        raise SystemExit(
            "error: numpy required for --embeddings; pip install numpy or make install-rag"
        ) from e
    arr = np.load(path)
    if arr.ndim != 2:
        raise SystemExit(f"error: expected 2D embeddings array, got shape {arr.shape}")
    return arr.astype(np.float32, copy=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import pr_comments.jsonl into review_rag.sqlite")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("export/pr_comments.jsonl"),
        help="Source JSONL",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("review_rag.sqlite"),
        help="SQLite database path",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=None,
        nargs="?",
        const=Path("export/rag_embed/embeddings.npy"),
        help="embeddings.npy (float16/float32); default path if flag present without value",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop chunks table and recreate before import",
    )
    args = parser.parse_args()

    inp = args.input.resolve()
    if not inp.is_file():
        print(f"error: file not found: {inp}", file=sys.stderr)
        return 2

    row_to_text = _row_to_text_loader()
    objs = _iter_comments(inp)
    if not objs:
        print("error: no rows in JSONL", file=sys.stderr)
        return 1

    emb_path: Path | None = args.embeddings
    if emb_path is not None:
        emb_path = emb_path.resolve()
        if not emb_path.is_file():
            print(f"error: embeddings file not found: {emb_path}", file=sys.stderr)
            return 2

    embeddings = _load_embeddings_npy(emb_path) if emb_path else None
    if embeddings is not None:
        if embeddings.shape[0] != len(objs):
            print(
                f"error: embeddings rows {embeddings.shape[0]} != jsonl chunks {len(objs)}",
                file=sys.stderr,
            )
            return 1

    db_path = args.db.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        if args.replace:
            cur.execute("DROP TABLE IF EXISTS chunks")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                meta TEXT NOT NULL,
                embedding BLOB
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
        if not args.replace:
            cur.execute("DELETE FROM chunks")

        batch: list[tuple[Any, ...]] = []
        for i, obj in enumerate(objs):
            source = _source_from_obj(obj)
            if not source:
                source = f"row_index:{i}"
            text = row_to_text(obj)
            meta = json.dumps(obj, ensure_ascii=False)
            blob: bytes | None = None
            if embeddings is not None:
                blob = embeddings[i].tobytes()
            batch.append((source, text, meta, blob))

        cur.executemany(
            "INSERT INTO chunks (source, text, meta, embedding) VALUES (?, ?, ?, ?)",
            batch,
        )
        con.commit()
        n = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        con.close()

    print(f"wrote {db_path} ({n} rows)", end="")
    if embeddings is not None:
        print(f", dim={embeddings.shape[1]}, dtype=float32 blob")
    else:
        print(", no embeddings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
