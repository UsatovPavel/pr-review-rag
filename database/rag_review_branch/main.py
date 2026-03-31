"""CLI и оркестрация: git diff → RAG → GigaChat / Yandex."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

from providers.gigachat_review_chat import DEFAULT_CHAT_URL, gigachat_chat_completions
from providers.yandex_review_chat import (
    DEFAULT_BASE_URL,
    resolve_yandex_model,
    yandex_chat_completions,
    yandex_folder_id,
)

from .constants import DEFAULT_SYSTEM, QUERY_TEXT_PREFIX
from .debug_dump import write_debug_llm_request
from .diff_validate import _added_lines_normalized, _invalid_path_line_anchors
from .env import _load_env, _repo_root
from .git_ops import _diff_tip, _git_diff, _git_diff_paths, _git_rev_parse, _resolve_base
from .repo_resolve import explain_review_repo_resolution, resolve_review_repo
from .request_cache import _request_cache_key, _save_request_cache, _try_load_request_cache
from .sqlite_embed import _db_fingerprint, _encode_query, _load_sqlite_embeddings


def main() -> int:
    _load_env()
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Branch review: RAG + LLM (GigaChat or Yandex AI Studio OpenAI-compatible API)"
    )
    parser.add_argument(
        "--git-repo",
        type=Path,
        default=None,
        help="Git repo to diff (default: GIT_REVIEW_REPO, иначе resolve как у export, иначе cwd)",
    )
    parser.add_argument(
        "--head-ref",
        default=None,
        metavar="REF",
        help="Правая сторона diff (default: GIT_LOG_REF или GIT_REVIEW_BRANCH, иначе HEAD — без checkout)",
    )
    parser.add_argument(
        "--upstream",
        default=os.environ.get("GIT_REVIEW_UPSTREAM", "origin/main"),
        help="Ref for merge-base (default: origin/main)",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Skip merge-base: use this commit SHA as left side of diff",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("review_rag_full.sqlite"),
        help="SQLite with chunks + embedding BLOB",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("export/rag_full_embed/manifest.json"),
        help="RAG manifest (model id, dim)",
    )
    parser.add_argument("--k", type=int, default=8, help="Top similar chunks")
    parser.add_argument("--max-diff-chars", type=int, default=100_000)
    parser.add_argument("-o", "--out", type=Path, default=Path("review.md"))
    parser.add_argument(
        "--llm",
        default=(os.environ.get("RAG_REVIEW_LLM") or "gigachat").strip().lower(),
        choices=["gigachat", "yandex", "alice"],
        help="LLM: gigachat | yandex | alice (alice = Yandex AI Studio, те же ключи что yandex)",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="ID",
        help="Model id (--llm gigachat: from GET /v1/models; yandex: gpt://... or short e.g. yandexgpt-5-pro/latest)",
    )
    _sys_default = (
        os.environ.get("RAG_REVIEW_SYSTEM_PROMPT", "").strip()
        or os.environ.get("GIGACHAT_SYSTEM_PROMPT", DEFAULT_SYSTEM)
    )
    parser.add_argument("--system", default=_sys_default)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verify for active LLM (GIGACHAT_SSL_VERIFY / YANDEX_SSL_VERIFY=0; dev only)",
    )
    parser.add_argument(
        "--no-request-cache",
        action="store_true",
        help="Do not read/write cache of RAG request prep (embed + top-k + rag_section)",
    )
    parser.add_argument(
        "--request-cache-dir",
        type=Path,
        default=None,
        help="Override RAG_REVIEW_REQUEST_CACHE_DIR (default: .cache/rag_review_request under repo root)",
    )
    parser.add_argument(
        "--debug-request",
        action="store_true",
        help="Write full system+user prompt to file (RAG_REVIEW_DEBUG_REQUEST=1; path: --debug-request-file)",
    )
    parser.add_argument(
        "--debug-request-file",
        type=Path,
        default=None,
        help="Debug dump path (default: .cache/rag_review_debug/last_llm_request.md under repo root)",
    )
    args = parser.parse_args()

    llm = args.llm

    if args.insecure:
        os.environ["GIGACHAT_SSL_VERIFY"] = "0"
        os.environ["YANDEX_SSL_VERIFY"] = "0"
    if (
        args.insecure
        or os.environ.get("GIGACHAT_SSL_VERIFY", "").strip() == "0"
        or os.environ.get("YANDEX_SSL_VERIFY", "").strip() == "0"
    ):
        print(
            "warning: LLM TLS verification disabled (--insecure или *SSL_VERIFY=0, dev only)",
            file=sys.stderr,
        )

    token = ""
    yandex_key = ""
    yandex_folder = ""
    chat_url = ""
    yandex_base = ""

    if llm == "gigachat":
        token = os.environ.get("GIGACHAT_ACCESS_TOKEN", "").strip()
        if not token:
            print(
                "error: GIGACHAT_ACCESS_TOKEN (make gigachat-token-insecure → .temp_env)",
                file=sys.stderr,
            )
            return 2
        model = (args.model or os.environ.get("GIGACHAT_MODEL", "GigaChat-2-Pro")).strip()
        temperature = float(os.environ.get("GIGACHAT_TEMPERATURE", "0.3"))
        chat_url = os.environ.get("GIGACHAT_CHAT_URL", "").strip() or DEFAULT_CHAT_URL
    else:
        yandex_key = os.environ.get("YANDEX_AI_STUDIO_API_KEY", "").strip()
        yandex_folder = yandex_folder_id()
        if not yandex_key:
            print("error: YANDEX_AI_STUDIO_API_KEY required for --llm yandex", file=sys.stderr)
            return 2
        if not yandex_folder:
            print(
                "error: YANDEX_FOLDER_ID (or YC_FOLDER_ID) required for --llm yandex",
                file=sys.stderr,
            )
            return 2
        model = resolve_yandex_model(args.model, yandex_folder)
        yt = os.environ.get("YANDEX_TEMPERATURE", "").strip()
        temperature = float(yt or os.environ.get("GIGACHAT_TEMPERATURE", "0.3"))
        yandex_base = os.environ.get("YANDEX_OPENAI_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
        chat_url = f"{yandex_base}/chat/completions"

    head_ref = (
        (args.head_ref or "").strip()
        or os.environ.get("GIT_REVIEW_BRANCH", "").strip()
        or os.environ.get("GIT_LOG_REF", "").strip()
        or None
    )
    head_tip = _diff_tip(head_ref)

    want_debug_request = args.debug_request or os.environ.get(
        "RAG_REVIEW_DEBUG_REQUEST", ""
    ).strip().lower() in ("1", "true", "yes")
    repo_resolution_note = ""

    if os.environ.get("GIT_REVIEW_REPO", "").strip():
        raw_repo = os.environ["GIT_REVIEW_REPO"].strip()
        repo = Path(raw_repo).expanduser().resolve()
        if want_debug_request:
            repo_resolution_note = (
                "### Откуда взят путь к git repo\n"
                f"- Переменная **`GIT_REVIEW_REPO`** (после `env._load_env` / `.env`).\n"
                f"- Значение: `{raw_repo}` → `{repo}`."
            )
    elif args.git_repo is not None:
        repo = args.git_repo.expanduser().resolve()
        if want_debug_request:
            repo_resolution_note = (
                "### Откуда взят путь к git repo\n"
                f"- Аргумент **`--git-repo`** → `{repo}`."
            )
    else:
        trace = explain_review_repo_resolution(root) if want_debug_request else ""
        resolved, res_err = resolve_review_repo(root)
        if resolved is not None:
            repo = resolved
            gh = os.environ.get("GITHUB_REPOSITORY", "").strip()
            if gh:
                print(f"git repo: {repo} (resolve_git_log_repo, GITHUB_REPOSITORY={gh!r})", flush=True)
            else:
                print(f"git repo: {repo} (resolve_git_log_repo)", flush=True)
            repo_resolution_note = trace
        else:
            repo = Path.cwd().resolve()
            if want_debug_request:
                repo_resolution_note = trace
                if res_err:
                    repo_resolution_note += f"\n- Ошибка resolve: {res_err}"
                repo_resolution_note += f"\n- **Фактически для diff:** `cwd` → `{repo}`."
            if os.environ.get("GITHUB_REPOSITORY", "").strip():
                msg = "GITHUB_REPOSITORY set but clone path not resolved."
                if res_err:
                    msg += f" {res_err}"
                msg += " Задайте GIT_REVIEW_REPO (см. database/rag_review_branch/repo_resolve.py)."
                print(f"warning: {msg}", file=sys.stderr)

    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        print(f"error: not a git repo: {repo}", file=sys.stderr)
        return 2

    print(f"git diff range: {repo}  merge-base→{head_tip!r} (upstream {args.upstream!r})", flush=True)

    base_sha, base_note = _resolve_base(repo, args.upstream, args.base, head_ref)
    diff_full = _git_diff(repo, base_sha, head_ref)
    truncated = False
    diff_for_model = diff_full
    if len(diff_for_model) > args.max_diff_chars:
        diff_for_model = diff_for_model[: args.max_diff_chars]
        truncated = True

    diff_empty = not diff_for_model.strip()
    head_sha = _git_rev_parse(repo, head_tip)
    if diff_empty:
        hint = (
            "warning: **git diff пустой** (`git diff <base>..<tip>` не показывает изменений). "
            "В LLM уходит только RAG по пустому диффу — ревью по коду бессмысленно.\n"
            f"  Репо: {repo}  tip: {head_tip!r}  база: {base_sha[:12]}… ({base_note})  upstream: {args.upstream!r}\n"
            "  Проверьте: **`GIT_LOG_REF`** / **`--head-ref`**, fetch, **`GIT_REVIEW_REPO`** / **`GITHUB_REPOSITORY`**, **`--base`** / **`--upstream`**.\n"
        )
        if head_sha and head_sha == base_sha:
            hint += "  (tip и база — один коммит: нет отличий ветки от merge-base.)\n"
        print(hint, file=sys.stderr, flush=True)

    manifest_path = (root / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest
    embed_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    if manifest_path.is_file():
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            embed_model = man.get("model") or embed_model
            exp_dim = man.get("dim")
        except (OSError, json.JSONDecodeError):
            exp_dim = None
    else:
        exp_dim = None

    db_path = args.db if args.db.is_absolute() else root / args.db
    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 2

    db_fp = _db_fingerprint(db_path)

    use_req_cache = not args.no_request_cache and os.environ.get(
        "RAG_REVIEW_NO_REQUEST_CACHE", ""
    ).strip().lower() not in ("1", "true", "yes")

    cache_dir = args.request_cache_dir
    if cache_dir is None:
        raw = os.environ.get("RAG_REVIEW_REQUEST_CACHE_DIR", "").strip()
        cache_dir = Path(raw) if raw else root / ".cache/rag_review_request"
    cache_dir = cache_dir.resolve()

    req_key = _request_cache_key(diff_for_model, embed_model, db_fp, args.k)
    cache_file = cache_dir / f"{req_key}.json"

    rag_section: str | None = None
    k = args.k
    if use_req_cache:
        hit = _try_load_request_cache(cache_file)
        if hit is not None:
            rag_section, k_cached = hit
            if k_cached > 0:
                k = k_cached
            print(f"request cache hit ({cache_file.name}), пропуск эмбеддинга и SQLite", flush=True)

    if rag_section is None:
        E, metas = _load_sqlite_embeddings(db_path)
        if exp_dim is not None and E.shape[1] != int(exp_dim):
            print(
                f"warning: SQLite dim {E.shape[1]} != manifest dim {exp_dim}",
                file=sys.stderr,
            )

        k = min(args.k, len(metas))
        query_text = QUERY_TEXT_PREFIX + diff_for_model
        print("Загрузка sentence-transformers для запроса...", flush=True)
        q = _encode_query(query_text, embed_model)
        sim = E @ q
        top_idx = np.argsort(-sim)[:k]

        rag_blocks: list[str] = []
        for rank, j in enumerate(top_idx, 1):
            m = metas[int(j)]
            rag_blocks.append(
                f"#### [{rank}] similarity={float(sim[j]):.4f} source={m.get('source', '')}\n\n"
                f"{m.get('text', '')}\n"
            )
        rag_section = "\n".join(rag_blocks)

        if use_req_cache:
            _save_request_cache(cache_file, rag_section, k)
            print(f"request cache saved ({cache_file.name})", flush=True)

    if diff_empty:
        diff_in_prompt = (
            "**Дифф пуст.** Между выбранной базой и правым ref нет изменений в `git diff`. "
            "Не придумывай `path:line`. Кратко: сравнивать нечего или проверьте `GIT_LOG_REF` / `GITHUB_REPOSITORY` / `GIT_REVIEW_REPO`.\n"
        )
    else:
        diff_in_prompt = "```diff\n" + diff_for_model + "\n```\n"

    user_content = (
        "### Инструкция по ответу\n\n"
        "Каждое замечание — пункт списка; первая строка: `path:line` (новая версия, строки с `+` в diff ниже). "
        "В тексте пункта — конкретика: что изменилось, какой риск или нарушение контракта; без шаблонов "
        "«проверьте/убедитесь/если нужно». Не добавляй пункт, если нечего сказать по видимому diff. "
        "Не ссылайся на код вне «Текущий diff».\n\n"
        "### Похожие прошлые замечания\n\n"
        + rag_section
        + "\n\n### Текущий diff\n\n"
        + diff_in_prompt
    )

    messages = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": user_content},
    ]

    if want_debug_request:
        dbg_path = args.debug_request_file
        if dbg_path is None:
            raw_dbg = os.environ.get("RAG_REVIEW_DEBUG_REQUEST_FILE", "").strip()
            dbg_path = Path(raw_dbg) if raw_dbg else root / ".cache/rag_review_debug/last_llm_request.md"
        if not dbg_path.is_absolute():
            dbg_path = root / dbg_path
        dbg_path = dbg_path.resolve()
        if repo_resolution_note.strip():
            print("debug: git repo resolution:\n" + repo_resolution_note, flush=True)
        write_debug_llm_request(
            dbg_path,
            llm=llm,
            model=model,
            temperature=temperature,
            chat_url=chat_url,
            repo=repo,
            base_sha=base_sha,
            base_note=base_note,
            upstream=args.upstream,
            embed_model=embed_model,
            k=k,
            diff_chars=len(diff_for_model),
            diff_truncated=truncated,
            rag_section_chars=len(rag_section),
            system_prompt=args.system,
            user_content=user_content,
            repo_resolution=repo_resolution_note,
        )
        print(f"debug: LLM request dump → {dbg_path}", flush=True)

    if llm == "gigachat":
        print(f"POST {chat_url} (GigaChat)...", flush=True)
        answer = gigachat_chat_completions(
            messages,
            model=model,
            temperature=temperature,
            chat_url=chat_url,
            token=token,
        )
    else:
        print(f"POST {chat_url} (Yandex)...", flush=True)
        answer = yandex_chat_completions(
            messages,
            model=model,
            temperature=temperature,
            api_key=yandex_key,
            folder_id=yandex_folder,
        )

    paths = _git_diff_paths(repo, base_sha, head_ref)
    added_lines = _added_lines_normalized(diff_for_model)
    invalid_anchors = _invalid_path_line_anchors(answer, added_lines, paths)
    out = args.out if args.out.is_absolute() else root / args.out
    provider_title = "GigaChat" if llm == "gigachat" else "Yandex AI Studio"
    lines = [
        f"# Review (RAG + {provider_title})",
        "",
        f"- git repo: `{repo}`",
        f"- diff tip: `{head_tip}` (`GIT_REVIEW_BRANCH` / `GIT_LOG_REF` / `--head-ref` или HEAD)",
        f"- base: `{base_sha}` ({base_note})",
        f"- upstream hint: `{args.upstream}`",
        f"- SQLite: `{db_path.name}`",
        f"- top_k: {k}, embed model: `{embed_model}`",
        f"- LLM: `{llm}`",
        f"- model: `{model}`",
        f"- chat URL: `{chat_url}`",
    ]
    if llm == "yandex":
        lines.append(f"- Yandex folder: `{yandex_folder}`")
    lines.append(f"- added-line anchors in diff (path:line for `+` rows): **{len(added_lines)}** pairs")
    if diff_empty:
        lines.append(
            "- **warning:** unified diff **пуст** — задайте ветку в **`GIT_LOG_REF`**, клон в **`GIT_REVIEW_REPO`** или **`GITHUB_REPOSITORY`** (origin)"
        )
    if truncated:
        lines.append(
            f"- **warning:** diff truncated to {args.max_diff_chars} chars (see GIT_REVIEW / max-diff-chars)"
        )
    if paths:
        lines.append("")
        lines.append("## Files touched (git)")
        for p in paths[:200]:
            lines.append(f"- `{p}`")
        if len(paths) > 200:
            lines.append(f"- … and {len(paths) - 200} more")
    if invalid_anchors:
        lines.append("")
        lines.append("## Валидация path:line")
        lines.append(
            "Следующие якоря в ответе модели **не** соответствуют строкам с `+` "
            f"в переданном diff ({len(invalid_anchors)} шт.):"
        )
        for a in invalid_anchors[:80]:
            lines.append(f"- {a}")
        if len(invalid_anchors) > 80:
            lines.append(f"- … and {len(invalid_anchors) - 80} more")
    lines.extend(["", "---", "", answer.strip(), ""])
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0
