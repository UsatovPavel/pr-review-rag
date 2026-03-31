#!/usr/bin/env python3
"""
Orchestrator: GitHub PR export + optional git history tree JSONL.

- GitHub: see `github_pulls.py` (pulls, comments, reviews).
- History tree: see `git_history_tree_export.py` — `git log --all` + parents; `GIT_LOG_REF` → `on_ref`.
  Output default `export/git_history_tree.jsonl` (env `GIT_HISTORY_TREE_OUT`). Skipped with `--no-git-history-tree`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from github_pulls import GitHubExportConfig, parse_owner_repo, run_github_export
from git_history_tree_export import (
    export_git_history_tree_jsonl,
    is_git_work_tree,
    resolve_git_log_repo,
)


def main() -> int:
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(
        description="Export GitHub PRs (+ comments) and optionally git history tree JSONL.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name for GitHub. Default: env GITHUB_REPOSITORY.",
    )
    parser.add_argument(
        "--state",
        choices=("all", "open", "closed"),
        default="all",
        help="GitHub pulls state (default: all).",
    )
    parser.add_argument(
        "--out",
        default="export/pulls.jsonl",
        help="Output JSONL for pulls.",
    )
    parser.add_argument(
        "--comments-out",
        default="export/pr_comments.jsonl",
        help="Output JSONL for issue + review comments + reviews.",
    )
    parser.add_argument(
        "--pulls-only",
        action="store_true",
        help="Only GitHub pulls list; skip comments/reviews.",
    )
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--raw", action="store_true")
    _ght_out = os.environ.get(
        "GIT_HISTORY_TREE_OUT",
        "export/git_history_tree.jsonl",
    )
    parser.add_argument(
        "--no-git-history-tree",
        "--no-git-log",
        action="store_true",
        dest="no_git_history_tree",
        help="Skip git history tree export.",
    )
    parser.add_argument(
        "--git-history-tree-out",
        "--git-log-out",
        default=_ght_out,
        dest="git_history_tree_out",
        help="History tree JSONL (default: GIT_HISTORY_TREE_OUT or export/git_history_tree.jsonl).",
    )
    parser.add_argument(
        "--git-history-tree-ref",
        "--git-log-ref",
        default=os.environ.get("GIT_LOG_REF", ""),
        dest="git_history_tree_ref",
        help="Tip for `on_ref`; empty = null (env GIT_LOG_REF).",
    )
    parser.add_argument(
        "--git-history-tree-max",
        "--git-log-max",
        type=int,
        default=int(os.environ.get("GIT_LOG_MAX", "0")),
        dest="git_history_tree_max",
        help="Max commits, 0 = no limit (env GIT_LOG_MAX).",
    )
    parser.add_argument(
        "--git-history-tree-reflog",
        "--git-log-reflog",
        action="store_true",
        dest="git_history_tree_reflog",
        help="git log --reflog (or GIT_LOG_REFLOG=1).",
    )
    parser.add_argument(
        "--git-history-tree-repo",
        "--git-log-repo",
        default=os.environ.get("GIT_REVIEW_REPO", ""),
        dest="git_history_tree_repo",
        help="App clone path override (env GIT_REVIEW_REPO; see git_history_tree_export).",
    )
    args = parser.parse_args()

    parsed = parse_owner_repo(args.repo or "")
    if not parsed:
        print("error: pass owner/repo or set GITHUB_REPOSITORY=owner/repo", file=sys.stderr)
        return 2
    owner, name = parsed

    gh_cfg = GitHubExportConfig(
        owner=owner,
        repo=name,
        state=args.state,
        out=args.out,
        comments_out=args.comments_out,
        pulls_only=args.pulls_only,
        per_page=args.per_page,
        raw=args.raw,
    )
    pull_count, comment_count = run_github_export(gh_cfg)
    print(f"wrote {pull_count} pulls to {gh_cfg.out}")
    if gh_cfg.pulls_only:
        print("skipped comments (--pulls-only)")
    else:
        print(f"wrote {comment_count} comment/review rows to {gh_cfg.comments_out}")

    if args.no_git_history_tree:
        print("skipped git history tree (--no-git-history-tree)")
        return 0

    git_out = Path(args.git_history_tree_out)
    if args.git_history_tree_repo.strip():
        repo = Path(args.git_history_tree_repo).expanduser().resolve()
        if not is_git_work_tree(repo):
            print(f"error: not a git work tree: {repo}", file=sys.stderr)
            return 2
    else:
        repo, err = resolve_git_log_repo(
            Path(__file__).resolve().parent,
            github_repository=args.repo,
        )
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        if repo is None:
            print(
                "warning: skipped git history tree — could not resolve app repo; "
                "set GIT_REVIEW_REPO or --git-history-tree-repo",
                file=sys.stderr,
            )
            return 0

    gl_reflog = args.git_history_tree_reflog or os.environ.get(
        "GIT_LOG_REFLOG", ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        n = export_git_history_tree_jsonl(
            repo,
            args.git_history_tree_ref,
            max(0, args.git_history_tree_max),
            git_out,
            include_reflog=gl_reflog,
        )
    except RuntimeError as e:
        print(f"error: git history tree: {e}", file=sys.stderr)
        return 1
    print(f"wrote {n} commits to {git_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
