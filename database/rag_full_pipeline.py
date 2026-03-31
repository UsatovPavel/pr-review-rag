#!/usr/bin/env python3
"""
Полный RAG-корпус из export/: pr_comments, pulls, git_history_tree, commit_diffs.

Не заменяет providers/local_rag_embeddings.py (только PR-комментарии).

Подкоманды:
  corpus — собрать export/rag_corpus.jsonl
  embed  — эмбеддинги в export/rag_full_embed/ (нужен install-rag)
  sqlite — залить в review_rag_full.sqlite
  all    — corpus → embed → sqlite

Пример: python database/rag_full_pipeline.py all --replace
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

try:
    from tqdm import tqdm as _tqdm
except ImportError:
    _tqdm = None  # type: ignore[misc, assignment]

T = TypeVar("T")


def _maybe_tqdm(it: Iterable[T], **kwargs: Any) -> Iterable[T]:
    if _tqdm is not None:
        return _tqdm(it, **kwargs)
    return it


# --- corpus: текст для эмбеддинга / SQLite ---------------------------------


def text_pr_comment(obj: dict[str, Any]) -> str:
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


def text_pull(obj: dict[str, Any]) -> str:
    lines = [
        f"PR metadata #{obj.get('number', '')}",
        f"title: {obj.get('title', '')}",
        f"state: {obj.get('state', '')} draft={obj.get('draft', '')}",
        f"user: {obj.get('user_login', '')}",
        f"head: {obj.get('head_ref', '')} @ {obj.get('head_sha', '')}",
        f"base: {obj.get('base_ref', '')} @ {obj.get('base_sha', '')}",
        f"created: {obj.get('created_at', '')} updated: {obj.get('updated_at', '')}",
        f"url: {obj.get('html_url', '')}",
    ]
    return "\n".join(lines)


def text_git_commit(obj: dict[str, Any]) -> str:
    parents = obj.get("parents")
    if isinstance(parents, list):
        p = " ".join(parents)
    else:
        p = str(parents or "")
    lines = [
        f"commit {obj.get('sha', '')}",
        f"parents: {p}",
        f"date: {obj.get('date', '')}",
        f"ref: {obj.get('ref', '')} on_ref={obj.get('on_ref', '')}",
        f"subject: {obj.get('subject', '')}",
        f"body:\n{obj.get('body') or ''}",
    ]
    return "\n".join(lines)


def text_commit_patch(obj: dict[str, Any]) -> str:
    patch = obj.get("patch_text") or ""
    lines = [
        f"commit patch {obj.get('sha', '')}",
        f"date: {obj.get('date', '')}",
        f"subject: {obj.get('subject', '')}",
        f"parents: {obj.get('parents', '')}",
        f"patch_file: {obj.get('patch_file', '')}",
        "patch:\n" + patch,
    ]
    return "\n".join(lines)


def record_to_text(obj: dict[str, Any]) -> str:
    rs = obj.get("rag_source")
    if rs == "pr_comment":
        return text_pr_comment(obj)
    if rs == "pull":
        return text_pull(obj)
    if rs == "git_commit":
        return text_git_commit(obj)
    if rs == "commit_patch":
        return text_commit_patch(obj)
    raise ValueError(f"unknown rag_source: {rs!r}")


def record_source(obj: dict[str, Any]) -> str:
    rs = obj.get("rag_source")
    if rs == "pr_comment":
        u = obj.get("html_url")
        if isinstance(u, str) and u.strip():
            return u.strip()
        pr = obj.get("pr")
        return f"PR #{pr}" if pr is not None else "pr_comment"
    if rs == "pull":
        u = obj.get("html_url")
        if isinstance(u, str) and u.strip():
            return u.strip()
        n = obj.get("number")
        return f"pull:{n}" if n is not None else "pull"
    if rs == "git_commit":
        sha = obj.get("sha")
        return f"commit:{sha}" if sha else "git_commit"
    if rs == "commit_patch":
        sha = obj.get("sha")
        return f"patch:{sha}" if sha else "commit_patch"
    return "unknown"


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def cmd_corpus(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    out = Path(args.out_corpus).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    max_patch = int(args.max_patch_chars)

    pc = root / args.pr_comments
    if pc.is_file():
        for obj in iter_jsonl(pc):
            r = dict(obj)
            r["rag_source"] = "pr_comment"
            records.append(r)
        print(f"pr_comments: {sum(1 for x in records if x.get('rag_source') == 'pr_comment')}")
    else:
        print(f"skip (missing): {pc}", file=sys.stderr)

    pl = root / args.pulls
    if pl.is_file():
        n0 = len(records)
        for obj in iter_jsonl(pl):
            r = dict(obj)
            r["rag_source"] = "pull"
            records.append(r)
        print(f"pulls: {len(records) - n0}")
    else:
        print(f"skip (missing): {pl}", file=sys.stderr)

    gh = root / args.git_history
    if gh.is_file():
        n0 = len(records)
        for obj in iter_jsonl(gh):
            r = dict(obj)
            r["rag_source"] = "git_commit"
            records.append(r)
        print(f"git_history_tree: {len(records) - n0}")
    else:
        print(f"skip (missing): {gh}", file=sys.stderr)

    idx = root / args.commit_diffs_index
    if idx.is_file():
        n0 = len(records)
        index_rows = list(iter_jsonl(idx))
        for row in _maybe_tqdm(
            index_rows,
            desc="commit_diffs",
            unit="commit",
            total=len(index_rows),
        ):
            sha = row.get("sha")
            rel = row.get("patch_file")
            patch_path = root / rel if isinstance(rel, str) else None
            patch_text = ""
            truncated = False
            if patch_path and patch_path.is_file():
                raw = patch_path.read_text(encoding="utf-8", errors="replace")
                if len(raw) > max_patch:
                    patch_text = raw[:max_patch]
                    truncated = True
                else:
                    patch_text = raw
            elif rel:
                print(f"warning: patch missing for {sha}: {patch_path}", file=sys.stderr)
            rec = {
                "rag_source": "commit_patch",
                "sha": sha,
                "parents": row.get("parents"),
                "date": row.get("date"),
                "subject": row.get("subject"),
                "patch_file": rel,
                "byte_size": row.get("byte_size"),
                "patch_text": patch_text,
                "patch_truncated": truncated,
            }
            records.append(rec)
        print(f"commit_diffs: {len(records) - n0}")
    else:
        print(f"skip (missing): {idx}", file=sys.stderr)

    if not records:
        print("error: corpus empty (no input files?)", file=sys.stderr)
        return 1

    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(records)} records)")
    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    inp = Path(args.input_corpus).resolve()
    if not inp.is_file():
        print(f"error: corpus not found: {inp}", file=sys.stderr)
        return 2

    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        from tqdm import tqdm
    except ImportError:
        print("error: pip install -r requirements-rag.txt", file=sys.stderr)
        return 2

    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    with open(inp, "r", encoding="utf-8") as f:
        for line in tqdm(f, desc="read corpus", unit="line"):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(record_to_text(obj))
            metas.append(
                {
                    "i": len(metas),
                    "rag_source": obj.get("rag_source"),
                    "sha": obj.get("sha"),
                    "pr": obj.get("pr"),
                    "number": obj.get("number"),
                    "html_url": obj.get("html_url"),
                }
            )

    if not texts:
        print("error: no rows", file=sys.stderr)
        return 1

    n = len(texts)
    print(f"chunks: {n}", flush=True)
    out_dir = Path(args.out_embed_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Загрузка модели {args.model!r} (первый запуск может долго качать веса)...",
        flush=True,
    )
    model = SentenceTransformer(args.model)
    dim = model.get_sentence_embedding_dimension()
    print(f"model dim: {dim}", flush=True)

    all_emb: list[Any] = []
    bs = int(args.batch_size)
    with tqdm(total=n, desc="encode", unit="chunk") as pbar:
        for start in range(0, n, bs):
            batch = texts[start : start + bs]
            e = model.encode(
                batch,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            all_emb.append(e.astype("float16"))
            pbar.update(len(batch))

    embeddings = np.vstack(all_emb)
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
        "pipeline": "rag_full_pipeline embed",
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_dir}")
    return 0


def cmd_sqlite(args: argparse.Namespace) -> int:
    try:
        import numpy as np
    except ImportError:
        print("error: pip install numpy", file=sys.stderr)
        return 2

    inp = Path(args.input_corpus).resolve()
    if not inp.is_file():
        print(f"error: corpus not found: {inp}", file=sys.stderr)
        return 2

    emb_path = Path(args.embeddings).resolve() if args.embeddings else None
    embeddings = None
    if emb_path is not None:
        if not emb_path.is_file():
            print(f"error: embeddings not found: {emb_path}", file=sys.stderr)
            return 2
        embeddings = np.load(emb_path).astype(np.float32, copy=False)

    objs: list[dict[str, Any]] = []
    with open(inp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                objs.append(json.loads(line))

    if not objs:
        print("error: empty corpus", file=sys.stderr)
        return 1

    if embeddings is not None and embeddings.shape[0] != len(objs):
        print(
            f"error: embeddings {embeddings.shape[0]} != corpus {len(objs)}",
            file=sys.stderr,
        )
        return 1

    db_path = Path(args.db).resolve()
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
            src = record_source(obj)
            txt = record_to_text(obj)
            meta = json.dumps(obj, ensure_ascii=False)
            blob = embeddings[i].tobytes() if embeddings is not None else None
            batch.append((src, txt, meta, blob))
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
        print(f", dim={embeddings.shape[1]}")
    else:
        print(", no embeddings")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    rc = cmd_corpus(args)
    if rc != 0:
        return rc
    rc = cmd_embed(args)
    if rc != 0:
        return rc
    args.embeddings = str(Path(args.out_embed_dir).resolve() / "embeddings.npy")
    return cmd_sqlite(args)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    p = argparse.ArgumentParser(description="Full RAG corpus from export/")
    p.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repo root (default: parent of database/)",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("corpus", help="Build export/rag_corpus.jsonl")
    pc.add_argument("--out-corpus", default="export/rag_corpus.jsonl")
    pc.add_argument("--pr-comments", default="export/pr_comments.jsonl")
    pc.add_argument("--pulls", default="export/pulls.jsonl")
    pc.add_argument("--git-history", default="export/git_history_tree.jsonl")
    pc.add_argument(
        "--commit-diffs-index",
        default="export/commit_diffs/index.jsonl",
    )
    pc.add_argument(
        "--max-patch-chars",
        type=int,
        default=120_000,
        help="Truncate patch text per commit (embedding/model limits)",
    )
    pc.set_defaults(func=cmd_corpus)

    pe = sub.add_parser("embed", help="Encode corpus → export/rag_full_embed/")
    pe.add_argument("--input-corpus", default="export/rag_corpus.jsonl")
    pe.add_argument("--out-embed-dir", default="export/rag_full_embed")
    pe.add_argument(
        "--model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    pe.add_argument("--batch-size", type=int, default=32)
    pe.set_defaults(func=cmd_embed)

    ps = sub.add_parser("sqlite", help="Import corpus (+ optional embeddings) to SQLite")
    ps.add_argument("--input-corpus", default="export/rag_corpus.jsonl")
    ps.add_argument("--db", default="review_rag_full.sqlite")
    ps.add_argument(
        "--embeddings",
        default=None,
        nargs="?",
        const="export/rag_full_embed/embeddings.npy",
        help="embeddings.npy; use flag without value for default path",
    )
    ps.add_argument("--replace", action="store_true")
    ps.set_defaults(func=cmd_sqlite)

    pa = sub.add_parser("all", help="corpus + embed + sqlite")
    pa.add_argument("--out-corpus", default="export/rag_corpus.jsonl")
    pa.add_argument("--pr-comments", default="export/pr_comments.jsonl")
    pa.add_argument("--pulls", default="export/pulls.jsonl")
    pa.add_argument("--git-history", default="export/git_history_tree.jsonl")
    pa.add_argument("--commit-diffs-index", default="export/commit_diffs/index.jsonl")
    pa.add_argument("--max-patch-chars", type=int, default=120_000)
    pa.add_argument("--input-corpus", default="export/rag_corpus.jsonl")
    pa.add_argument("--out-embed-dir", default="export/rag_full_embed")
    pa.add_argument(
        "--model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    pa.add_argument("--batch-size", type=int, default=32)
    pa.add_argument("--db", default="review_rag_full.sqlite")
    pa.add_argument("--replace", action="store_true")
    pa.set_defaults(func=cmd_all)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
