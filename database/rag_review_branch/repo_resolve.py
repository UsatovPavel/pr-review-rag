"""Путь к клону приложения: явный GIT_REVIEW_REPO или GITHUB_REPOSITORY + совпадение git origin."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _is_git_work_tree(repo: Path) -> bool:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _origin_url(repo: Path) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        return None
    u = r.stdout.strip()
    return u or None


def _parse_github_repository(spec: str) -> tuple[str, str] | None:
    s = spec.strip()
    if "/" not in s:
        return None
    owner, _, name = s.partition("/")
    if not owner or not name:
        return None
    return owner, name


def _remote_matches_github_spec(remote_url: str, owner: str, repo: str) -> bool:
    """HTTPS / SSH к github.com (и аналоги в URL)."""
    r = remote_url.lower().replace(".git", "")
    o, n = owner.lower(), repo.lower()
    if f"github.com/{o}/{n}" in r:
        return True
    if f"github.com:{o}/{n}" in r:
        return True
    m = re.search(r"[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote_url.strip())
    if m and m.group(1).lower() == o and m.group(2).lower() == n:
        return True
    return False


def _candidate_matches_gh(candidate: Path, gh_spec: str) -> bool:
    parsed = _parse_github_repository(gh_spec)
    if not parsed:
        return False
    owner, repo = parsed
    if not _is_git_work_tree(candidate):
        return False
    url = _origin_url(candidate)
    if not url:
        return False
    return _remote_matches_github_spec(url, owner, repo)


def resolve_review_repo(
    pr_root: Path,
    *,
    github_repository: str | None = None,
) -> tuple[Path | None, str | None]:
    """
    Путь к репозиторию приложения для git diff.

    1) GIT_REVIEW_REPO — явный путь.
    2) GITHUB_REPOSITORY (env или override): кандидаты + совпадение `origin` с owner/repo:
       родитель корня pr-review-rag; sibling `родитель/repo_name`.
    3) Без GITHUB_REPOSITORY: если родитель pr-review-rag — git, взять его (export без env).
    """
    raw = os.environ.get("GIT_REVIEW_REPO", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        if _is_git_work_tree(p):
            return p, None
        return None, f"GIT_REVIEW_REPO is not a git work tree: {p}"

    gh = (github_repository or os.environ.get("GITHUB_REPOSITORY", "") or "").strip()
    pr_root = pr_root.resolve()
    parent = pr_root.parent

    if gh:
        parsed = _parse_github_repository(gh)
        if not parsed:
            return None, f"GITHUB_REPOSITORY invalid (expected owner/name): {gh!r}"
        _, repo_name = parsed

        for c in (parent, parent / repo_name):
            if _candidate_matches_gh(c, gh):
                return c, None

        return (
            None,
            f"no clone found for {gh!r} (parent of tooling + sibling by repo name vs origin); "
            "set GIT_REVIEW_REPO.",
        )

    if _is_git_work_tree(parent):
        return parent, None

    return None, None


def explain_review_repo_resolution(
    pr_root: Path,
    *,
    github_repository: str | None = None,
) -> str:
    """Текст для `--debug-request` (та же логика, что `resolve_review_repo`)."""
    lines: list[str] = ["### Откуда взят путь к git repo (`resolve_review_repo`)"]

    raw = os.environ.get("GIT_REVIEW_REPO", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        lines.append(f"- **`GIT_REVIEW_REPO`** = `{raw}` → `{p}`.")
        lines.append(f"- git work tree: **`{_is_git_work_tree(p)}`**.")
        return "\n".join(lines)

    gh = (github_repository or os.environ.get("GITHUB_REPOSITORY", "") or "").strip()
    pr_root = pr_root.resolve()
    parent = pr_root.parent
    lines.append(f"- **`GITHUB_REPOSITORY`** = `{gh or '(не задан)'}`.")

    if gh:
        parsed = _parse_github_repository(gh)
        if not parsed:
            lines.append("- Некорректный формат (нужен `owner/name`).")
            return "\n".join(lines)
        _, repo_name = parsed
        for label, c in (
            ("родитель корня pr-review-rag", parent),
            ("sibling `parent/repo_name`", parent / repo_name),
        ):
            lines.append(f"- Кандидат ({label}): `{c}`.")
            if not _is_git_work_tree(c):
                lines.append("  - не git work tree.")
                continue
            url = _origin_url(c)
            lines.append(f"  - `origin` = `{url or '(нет)'}`")
            ok = url and _remote_matches_github_spec(url, parsed[0], parsed[1])
            lines.append(f"  - совпадает с **`{gh}`**: **`{ok}`**")
            if ok:
                lines.append(f"- **Итог:** `{c}`.")
                return "\n".join(lines)

        lines.append("- **Итог:** путь не найден → в main подставляется **`cwd`**; задайте **`GIT_REVIEW_REPO`**.")
        return "\n".join(lines)

    lines.append(f"- Без `GITHUB_REPOSITORY`: пробуем родитель tooling `{parent}`.")
    lines.append(f"- git work tree: **`{_is_git_work_tree(parent)}`**.")
    if _is_git_work_tree(parent):
        lines.append(f"- **Итог:** `{parent}`.")
    else:
        lines.append("- **Итог:** не найден → **`cwd`**.")
    return "\n".join(lines)

