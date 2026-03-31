#!/usr/bin/env python3
"""
Export full patch per commit for the whole local repository (not one branch only).

Uses `git rev-list --all` so every commit reachable from any ref (branches, tags,
remotes, stash parents as refs, etc.) is included. Optional `--reflog` adds
`--reflog` to rev-list (more rewritten/squashed tips from reflog — not a guarantee
of “every object ever”, but wider than `--all` alone).

Override repo path like `git_history_tree_export.py`: GIT_REVIEW_REPO, GITHUB_REPOSITORY, etc.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from git_history_tree_export import is_git_work_tree, resolve_git_log_repo


def rev_list_all_shas(
    repo: Path,
    *,
    include_reflog: bool,
    max_commits: int | None,
    reverse: bool,
) -> list[str]:
    cmd = [
        "git",
        "-C",
        str(repo),
        "rev-list",
        "--all",
    ]
    if include_reflog:
        cmd.append("--reflog")
    if reverse:
        cmd.append("--reverse")
    if max_commits is not None and max_commits > 0:
        cmd.extend(["-n", str(max_commits)])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"rev-list exit {proc.returncode}")
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def commit_meta(repo: Path, sha: str) -> dict[str, str | None]:
    fmt = "%H%x1f%P%x1f%aI%x1f%s"
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--no-patch", f"--pretty=format:{fmt}", sha],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return {"sha": sha, "parents": None, "date": None, "subject": None}
    parts = proc.stdout.strip().split("\x1f", 3)
    if len(parts) < 4:
        return {"sha": sha, "parents": None, "date": None, "subject": None}
    return {
        "sha": parts[0],
        "parents": parts[1] or None,
        "date": parts[2],
        "subject": parts[3],
    }


def git_show_patch(repo: Path, sha: str) -> str:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "show",
            "--no-color",
            "--patch",
            "--no-textconv",
            sha,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show {sha}: {proc.stderr.strip()}")
    return proc.stdout


def main() -> int:
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")

    tooling = Path(__file__).resolve().parent
    default_gh = os.environ.get("GITHUB_REPOSITORY", "")

    parser = argparse.ArgumentParser(
        description="Export full `git show` patch for each commit (rev-list --all).",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GIT_REVIEW_REPO", ""),
        help="App clone path (default: resolve like git_history_tree_export).",
    )
    parser.add_argument(
        "--github-repository",
        default=default_gh,
        help="owner/name for path resolution if --repo unset (default: env).",
    )
    parser.add_argument(
        "--out-dir",
        default="export/commit_diffs",
        help="Output directory (default: export/commit_diffs).",
    )
    parser.add_argument(
        "--index",
        default="",
        help="Manifest JSONL (default: <out-dir>/index.jsonl).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=int(os.environ.get("COMMIT_DIFF_MAX", "0")),
        help="Max commits (0 = no limit). Env: COMMIT_DIFF_MAX.",
    )
    parser.add_argument(
        "--reflog",
        action="store_true",
        help="Pass --reflog to rev-list (wider set after rewrites).",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Oldest commits first (rev-list --reverse).",
    )
    args = parser.parse_args()

    if args.repo.strip():
        repo = Path(args.repo).expanduser().resolve()
        if not is_git_work_tree(repo):
            print(f"error: not a git work tree: {repo}", file=sys.stderr)
            return 2
    else:
        r, err = resolve_git_log_repo(
            tooling,
            github_repository=args.github_repository or None,
        )
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        if r is None:
            print(
                "error: set GIT_REVIEW_REPO or GITHUB_REPOSITORY (origin must match) for path resolution",
                file=sys.stderr,
            )
            return 2
        repo = r

    max_n = args.max if args.max > 0 else None
    try:
        shas = rev_list_all_shas(
            repo,
            include_reflog=args.reflog,
            max_commits=max_n,
            reverse=args.reverse,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    index_path = Path(args.index) if args.index.strip() else out_dir / "index.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    ok = 0
    with open(index_path, "w", encoding="utf-8") as idx:
        for i, sha in enumerate(shas, 1):
            try:
                patch = git_show_patch(repo, sha)
            except RuntimeError as e:
                print(f"warning: {e}", file=sys.stderr)
                continue
            patch_path = out_dir / f"{sha}.patch"
            patch_path.write_text(patch, encoding="utf-8")
            meta = commit_meta(repo, sha)
            meta["patch_file"] = str(patch_path.as_posix())
            meta["byte_size"] = len(patch.encode("utf-8"))
            idx.write(json.dumps(meta, ensure_ascii=False) + "\n")
            ok += 1
            if i % 200 == 0:
                print(f"... {i} commits", file=sys.stderr)

    print(f"rev-list: {len(shas)} commits, wrote {ok} patches under {out_dir}")
    print(f"manifest: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
