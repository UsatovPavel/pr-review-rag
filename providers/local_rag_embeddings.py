#!/usr/bin/env python3
"""
Локальные эмбеддинги для export/pr_comments.jsonl (как colab_rag_embeddings.ipynb).

Установка: pip install -r requirements-rag.txt

Выход: --out-dir/embeddings.npy (float16, L2-normalized), chunks_meta.jsonl, manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from tqdm import tqdm

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def row_to_text(obj: dict[str, Any]) -> str:
    parts = [
        f"PR #{obj.get('pr', '')}",
        f"kind: {obj.get('kind', '')}",
    ]
    if obj.get("path"):
        parts.append(f"file: {obj['path']}")
    if obj.get("line") is not None:
        parts.append(f"line: {obj['line']}")
    if obj.get("diff_hunk"):
        parts.append(f"diff:\n{obj['diff_hunk']}")
    parts.append(f"author: {obj.get('author', '')}")
    parts.append(obj.get("body") or "")
    return "\n".join(p for p in parts if p)


def load_chunks(path: Path, max_rows: int | None) -> tuple[list[str], list[dict[str, Any]]]:
    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in tqdm(enumerate(f), desc="read JSONL", unit="line"):
            if max_rows is not None and i >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(row_to_text(obj))
            metas.append(
                {
                    "i": len(metas),
                    "pr": obj.get("pr"),
                    "kind": obj.get("kind"),
                    "html_url": obj.get("html_url"),
                    "path": obj.get("path"),
                    "line": obj.get("line"),
                }
            )
    return texts, metas


def main() -> int:
    parser = argparse.ArgumentParser(description="Build sentence-transformers embeddings for PR comments JSONL.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("export/pr_comments.jsonl"),
        help="Input JSONL (default: export/pr_comments.jsonl)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("export/rag_embed"),
        help="Output directory (default: export/rag_embed)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="sentence-transformers model id")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-rows", type=int, default=None, help="Limit rows for testing")
    parser.add_argument(
        "--query",
        default="",
        help="If set, print top-5 similar chunks after encoding (debug)",
    )
    args = parser.parse_args()

    inp = args.input.resolve()
    if not inp.is_file():
        print(f"error: file not found: {inp}", file=sys.stderr)
        return 2

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "error: install RAG deps: pip install -r requirements-rag.txt",
            file=sys.stderr,
        )
        return 2

    texts, metas = load_chunks(inp, args.max_rows)
    if not texts:
        print("error: no rows loaded", file=sys.stderr)
        return 1
    n_chunks = len(texts)
    print(f"chunks: {n_chunks}", flush=True)

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Загрузка модели {args.model!r} (первый запуск может долго качать веса с Hugging Face)...",
        flush=True,
    )
    model = SentenceTransformer(args.model)
    dim = model.get_sentence_embedding_dimension()
    print(f"model dim: {dim}", flush=True)

    all_emb: list[np.ndarray] = []
    with tqdm(total=n_chunks, desc="encode", unit="chunk") as pbar:
        for start in range(0, n_chunks, args.batch_size):
            batch = texts[start : start + args.batch_size]
            e = model.encode(
                batch,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            all_emb.append(e.astype(np.float16))
            pbar.update(len(batch))

    embeddings = np.vstack(all_emb)
    print(f"embeddings: shape={embeddings.shape} dtype={embeddings.dtype}")

    np.save(out_dir / "embeddings.npy", embeddings)
    with open(out_dir / "chunks_meta.jsonl", "w", encoding="utf-8") as f:
        for m in metas:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    manifest = {
        "model": args.model,
        "dim": int(dim),
        "count": len(metas),
        "dtype": "float16",
        "normalized": True,
        "input_jsonl": str(inp),
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"saved: {out_dir}")

    if args.query.strip():
        q = model.encode(
            [args.query.strip()],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0].astype(np.float32)
        sim = embeddings.astype(np.float32) @ q
        top = np.argsort(-sim)[:5]
        print("top-5 for query:", args.query.strip())
        for rank, j in enumerate(top, 1):
            print(f"  {rank} sim={float(sim[j]):.4f} {metas[j]}")
            preview = texts[j][:320].replace("\n", " ")
            print(f"     {preview}...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
