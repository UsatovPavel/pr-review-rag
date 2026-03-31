"""SQLite chunks + эмбеддинги; запрос к sentence-transformers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _db_fingerprint(db_path: Path) -> str:
    st = db_path.stat()
    return f"{db_path.resolve()}|{st.st_size}|{st.st_mtime_ns}"


def _load_sqlite_embeddings(db_path: Path) -> tuple[np.ndarray, list[dict[str, Any]]]:
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT id, source, text, embedding FROM chunks WHERE embedding IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise SystemExit("error: no rows with embedding in SQLite")
    vecs: list[np.ndarray] = []
    meta: list[dict[str, Any]] = []
    dim: int | None = None
    for rid, source, text, blob in rows:
        if not blob:
            continue
        v = np.frombuffer(blob, dtype=np.float32)
        if dim is None:
            dim = int(v.shape[0])
        elif v.shape[0] != dim:
            raise SystemExit(f"error: embedding dim mismatch row id={rid}")
        n = float(np.linalg.norm(v))
        if n > 1e-12:
            v = v / n
        vecs.append(v.astype(np.float32))
        meta.append({"id": rid, "source": source, "text": text})
    if not vecs:
        raise SystemExit("error: empty embedding matrix")
    return np.stack(vecs, axis=0), meta


def _encode_query(text: str, model_id: str) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    m = SentenceTransformer(model_id)
    q = m.encode(
        [text],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )[0].astype(np.float32)
    return q
