"""Git: merge-base, diff, список путей."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _diff_tip(head_ref: str | None) -> str:
    """Правая сторона diff: ref или HEAD."""
    if head_ref and head_ref.strip():
        return head_ref.strip()
    return "HEAD"


def _resolve_base(
    repo: Path,
    upstream: str,
    base_explicit: str | None,
    head_ref: str | None,
) -> tuple[str, str]:
    """Returns (base_sha, note how resolved)."""
    if base_explicit:
        return base_explicit.strip(), f"explicit --base {base_explicit!r}"
    tip = _diff_tip(head_ref)
    tip_label = tip if (head_ref and head_ref.strip()) else "HEAD"
    up = upstream.strip() or "origin/main"
    p = _run_git(repo, "merge-base", tip, up)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip(), f"merge-base {tip_label} {up!r}"
    for alt in ("main", "master", "origin/master", "develop"):
        p2 = _run_git(repo, "merge-base", tip, alt)
        if p2.returncode == 0 and p2.stdout.strip():
            return p2.stdout.strip(), f"merge-base {tip_label} {alt!r} (fallback)"
    err = (p.stderr or p.stdout or "unknown").strip()
    raise SystemExit(f"error: git merge-base failed for {upstream!r} (tip={tip!r}): {err}")


def _git_diff(repo: Path, base: str, head_ref: str | None) -> str:
    tip = _diff_tip(head_ref)
    p = _run_git(repo, "diff", f"{base}..{tip}", "--no-color")
    if p.returncode != 0:
        raise SystemExit(
            f"error: git diff {base}..{tip}: {(p.stderr or '').strip()}\n"
            f"  hint: проверьте ref ветки (GIT_LOG_REF / --head-ref), fetch, локальное имя ветки."
        )
    return p.stdout


def _git_diff_paths(repo: Path, base: str, head_ref: str | None) -> list[str]:
    tip = _diff_tip(head_ref)
    p = _run_git(repo, "diff", f"{base}..{tip}", "--name-only", "--no-color")
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _git_rev_parse(repo: Path, ref: str) -> str:
    p = _run_git(repo, "rev-parse", ref)
    return p.stdout.strip() if p.returncode == 0 else ""
