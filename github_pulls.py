"""GitHub REST: pulls, issue comments, review comments, reviews → JSONL."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


def token_from_env() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch_pulls_page(
    client: httpx.Client,
    owner: str,
    repo: str,
    state: str,
    page: int,
    per_page: int,
) -> list[dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    params = {"state": state, "per_page": per_page, "page": page}
    r = client.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise TypeError(f"Expected list from pulls API, got {type(data)}")
    return data


def paginate_url(
    client: httpx.Client,
    url: str,
    per_page: int,
) -> list[dict[str, Any]]:
    page = 1
    out: list[dict[str, Any]] = []
    while True:
        r = client.get(url, params={"per_page": per_page, "page": page})
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list):
            raise TypeError(f"Expected list from {url}, got {type(batch)}")
        if not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def slim_pull(p: dict[str, Any]) -> dict[str, Any]:
    user = p.get("user") if isinstance(p.get("user"), dict) else {}
    head = p.get("head") if isinstance(p.get("head"), dict) else {}
    base = p.get("base") if isinstance(p.get("base"), dict) else {}
    return {
        "number": p.get("number"),
        "title": p.get("title"),
        "state": p.get("state"),
        "draft": p.get("draft"),
        "merged_at": p.get("merged_at"),
        "closed_at": p.get("closed_at"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "user_login": user.get("login"),
        "html_url": p.get("html_url"),
        "head_ref": head.get("ref"),
        "head_sha": head.get("sha"),
        "base_ref": base.get("ref"),
        "base_sha": base.get("sha"),
    }


def _login(user: Any) -> str | None:
    if isinstance(user, dict):
        return user.get("login")
    return None


def normalize_issue_comment(pr: int, c: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr": pr,
        "kind": "issue_comment",
        "author": _login(c.get("user")),
        "body": c.get("body") or "",
        "path": None,
        "line": None,
        "diff_hunk": None,
        "commit_id": None,
        "created_at": c.get("created_at"),
        "html_url": c.get("html_url"),
        "review_state": None,
    }


def normalize_review_comment(pr: int, c: dict[str, Any]) -> dict[str, Any]:
    line = c.get("line")
    if line is None:
        line = c.get("original_line")
    return {
        "pr": pr,
        "kind": "review_comment",
        "author": _login(c.get("user")),
        "body": c.get("body") or "",
        "path": c.get("path"),
        "line": line,
        "diff_hunk": c.get("diff_hunk"),
        "commit_id": c.get("commit_id"),
        "created_at": c.get("created_at"),
        "html_url": c.get("html_url"),
        "review_state": None,
    }


def normalize_review(pr: int, rev: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr": pr,
        "kind": "review",
        "author": _login(rev.get("user")),
        "body": rev.get("body") or "",
        "path": None,
        "line": None,
        "diff_hunk": None,
        "commit_id": rev.get("commit_id"),
        "created_at": rev.get("submitted_at"),
        "html_url": rev.get("html_url"),
        "review_state": rev.get("state"),
    }


def export_pr_comments(
    client: httpx.Client,
    owner: str,
    repo: str,
    pr_numbers: list[int],
    per_page: int,
    out_f,
) -> int:
    total = 0
    for n in pr_numbers:
        base = f"{GITHUB_API}/repos/{owner}/{repo}"
        for c in paginate_url(client, f"{base}/issues/{n}/comments", per_page):
            out_f.write(json.dumps(normalize_issue_comment(n, c), ensure_ascii=False) + "\n")
            total += 1
        for c in paginate_url(client, f"{base}/pulls/{n}/comments", per_page):
            out_f.write(json.dumps(normalize_review_comment(n, c), ensure_ascii=False) + "\n")
            total += 1
        for rev in paginate_url(client, f"{base}/pulls/{n}/reviews", per_page):
            out_f.write(json.dumps(normalize_review(n, rev), ensure_ascii=False) + "\n")
            total += 1
    return total


@dataclass(frozen=True)
class GitHubExportConfig:
    owner: str
    repo: str
    state: str
    out: str
    comments_out: str
    pulls_only: bool
    per_page: int
    raw: bool


def run_github_export(cfg: GitHubExportConfig) -> tuple[int, int]:
    """Returns (pull_count, comment_count)."""
    per_page = min(max(1, cfg.per_page), 100)
    token = token_from_env()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    os.makedirs(os.path.dirname(cfg.out) or ".", exist_ok=True)
    if not cfg.pulls_only:
        os.makedirs(os.path.dirname(cfg.comments_out) or ".", exist_ok=True)

    pull_numbers: list[int] = []
    pull_count = 0

    with httpx.Client(headers=headers, timeout=120.0) as client:
        with open(cfg.out, "w", encoding="utf-8") as pulls_f:
            page = 1
            while True:
                batch = fetch_pulls_page(
                    client, cfg.owner, cfg.repo, cfg.state, page, per_page
                )
                if not batch:
                    break
                for p in batch:
                    row = p if cfg.raw else slim_pull(p)
                    pulls_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    pull_count += 1
                    num = p.get("number")
                    if isinstance(num, int):
                        pull_numbers.append(num)
                if len(batch) < per_page:
                    break
                page += 1

        comment_count = 0
        if not cfg.pulls_only:
            with open(cfg.comments_out, "w", encoding="utf-8") as comments_f:
                comment_count = export_pr_comments(
                    client,
                    cfg.owner,
                    cfg.repo,
                    pull_numbers,
                    per_page,
                    comments_f,
                )

    return pull_count, comment_count


def parse_owner_repo(spec: str) -> tuple[str, str] | None:
    if not spec or "/" not in spec:
        return None
    owner, _, name = spec.partition("/")
    if not owner or not name:
        return None
    return owner, name


def github_main(argv: list[str] | None) -> int:
    """CLI entry for GitHub export only (same flags as legacy monolith)."""
    import argparse
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(
        description="Export GitHub PRs and related comments to JSONL.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name. Default: env GITHUB_REPOSITORY.",
    )
    parser.add_argument("--state", choices=("all", "open", "closed"), default="all")
    parser.add_argument("--out", default="export/pulls.jsonl")
    parser.add_argument("--comments-out", default="export/pr_comments.jsonl")
    parser.add_argument("--pulls-only", action="store_true")
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args(argv)

    parsed = parse_owner_repo(args.repo or "")
    if not parsed:
        print("error: pass owner/repo or set GITHUB_REPOSITORY=owner/repo", file=sys.stderr)
        return 2
    owner, name = parsed

    cfg = GitHubExportConfig(
        owner=owner,
        repo=name,
        state=args.state,
        out=args.out,
        comments_out=args.comments_out,
        pulls_only=args.pulls_only,
        per_page=args.per_page,
        raw=args.raw,
    )
    pull_count, comment_count = run_github_export(cfg)
    print(f"wrote {pull_count} pulls to {cfg.out}")
    if cfg.pulls_only:
        print("skipped comments (--pulls-only)")
    else:
        print(f"wrote {comment_count} comment/review rows to {cfg.comments_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(github_main(None))
