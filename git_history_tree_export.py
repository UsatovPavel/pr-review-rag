"""Export commit graph + messages from a local clone to JSONL.

Always walks **all** refs: `git log --all` with `%P` parents (same idea as `rev-list --all --parents`).

Set `GIT_LOG_REF` to a branch/ref name to add **`on_ref`**: whether each commit is reachable
from that tip (`git rev-list <ref>`). If unset, `on_ref` and `ref` are JSON `null`.

Env: `GIT_LOG_REF`, `GIT_LOG_MAX` (0 = no limit), `GIT_LOG_REFLOG=1` / `--reflog`.

Path resolution: `GITHUB_REPOSITORY`, `GIT_LOG_REPO`, etc. (see `resolve_git_log_repo`).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def is_git_work_tree(repo: Path) -> bool:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _repo_name_from_github_spec(spec: str) -> str | None:
    spec = spec.strip()
    if "/" not in spec:
        return None
    _, _, name = spec.partition("/")
    return name or None


def resolve_git_log_repo(
    tooling_dir: Path,
    *,
    github_repository: str | None = None,
) -> tuple[Path | None, str | None]:
    """
    Returns (repo_path, error_message).
    Priority: GIT_LOG_REPO → parent(tooling_dir) if git → sibling tooling_dir.parent/repo_name
    from GITHUB_REPOSITORY → GIT_LOG_ROOT/repo_name.
    """
    raw = os.environ.get("GIT_LOG_REPO", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        if is_git_work_tree(p):
            return p, None
        return None, f"GIT_LOG_REPO is not a git work tree: {p}"

    gh = (github_repository or os.environ.get("GITHUB_REPOSITORY", "") or "").strip()
    repo_name = _repo_name_from_github_spec(gh)

    parent = tooling_dir.resolve().parent
    if is_git_work_tree(parent):
        return parent, None

    if repo_name:
        sibling = parent / repo_name
        if is_git_work_tree(sibling):
            return sibling, None

        root = os.environ.get("GIT_LOG_ROOT", "").strip()
        if root:
            candidate = Path(root).expanduser().resolve() / repo_name
            if is_git_work_tree(candidate):
                return candidate, None
            return (
                None,
                f"GIT_LOG_ROOT/{repo_name} is not a git work tree: {candidate}",
            )

    return None, None


def _mark_ref_name(raw: str) -> str | None:
    """Branch/ref used for `on_ref`; None = do not mark."""
    r = raw.strip()
    if not r or r.lower() in ("all", "*"):
        return None
    return r


def collect_reachable_shas(repo: Path, tip: str) -> frozenset[str]:
    """All commits reachable from `tip` (ancestors of the tip)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-list", tip],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"rev-list {tip!r} exit {proc.returncode}")
    return frozenset(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())


def export_git_history_tree_jsonl(
    repo: Path,
    mark_ref: str,
    max_commits: int,
    out_path: Path,
    *,
    include_reflog: bool = False,
) -> int:
    """Each line: sha, parents, date, subject, body, ref (mark tip or null), on_ref (bool or null)."""
    tip = _mark_ref_name(mark_ref)
    reachable: frozenset[str] | None = None
    if tip is not None:
        reachable = collect_reachable_shas(repo, tip)

    pretty = "%H%x1f%P%x1f%aI%x1f%s%x1f%b%x1e"
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "--all",
        f"--pretty=format:{pretty}",
    ]
    if include_reflog:
        cmd.append("--reflog")
    if max_commits > 0:
        cmd.extend(["-n", str(max_commits)])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git log exit {proc.returncode}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for raw in proc.stdout.split("\x1e"):
            chunk = raw.strip()
            if not chunk:
                continue
            parts = chunk.split("\x1f", 4)
            if len(parts) < 4:
                continue
            sha, parents_raw, date, subject = parts[0], parts[1], parts[2], parts[3]
            body = parts[4] if len(parts) > 4 else ""
            parents = [p for p in parents_raw.split() if p]
            on_ref: bool | None
            if reachable is None:
                on_ref = None
            else:
                on_ref = sha in reachable
            row = {
                "sha": sha,
                "parents": parents,
                "date": date,
                "subject": subject,
                "body": body.strip(),
                "ref": tip,
                "on_ref": on_ref,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def git_history_tree_main(argv: list[str] | None) -> int:
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="Export git history tree (graph + messages) to JSONL.")
    parser.add_argument(
        "--out",
        default=os.environ.get("GIT_HISTORY_TREE_OUT", "export/git_history_tree.jsonl"),
        help="Output path (default: export/git_history_tree.jsonl or GIT_HISTORY_TREE_OUT).",
    )
    parser.add_argument(
        "--ref",
        default=os.environ.get("GIT_LOG_REF", ""),
        help="Tip ref for `on_ref` (reachability); empty = on_ref null. Log is always --all.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=int(os.environ.get("GIT_LOG_MAX", "0")),
        help="Max commits, 0 = no limit (default: env GIT_LOG_MAX or 0).",
    )
    parser.add_argument(
        "--reflog",
        action="store_true",
        help="Add --reflog to git log (or set env GIT_LOG_REFLOG=1).",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GIT_LOG_REPO", ""),
        help="Override path to app clone (default: infer from GITHUB_REPOSITORY; see module doc).",
    )
    args = parser.parse_args(argv)

    repo: Path | None
    err: str | None
    if args.repo.strip():
        repo = Path(args.repo).expanduser().resolve()
        if not is_git_work_tree(repo):
            print(f"error: not a git work tree: {repo}", file=sys.stderr)
            return 2
        err = None
    else:
        repo, err = resolve_git_log_repo(Path(__file__).resolve().parent)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        if repo is None:
            print(
                "error: could not resolve app repo: set GITHUB_REPOSITORY, or GIT_LOG_REPO / --repo, "
                "or GIT_LOG_ROOT (with GITHUB_REPOSITORY for folder name)",
                file=sys.stderr,
            )
            return 2

    out_path = Path(args.out)
    reflog = args.reflog or os.environ.get("GIT_LOG_REFLOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        n = export_git_history_tree_jsonl(
            repo,
            args.ref,
            max(0, args.max),
            out_path,
            include_reflog=reflog,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {n} commits to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(git_history_tree_main(None))
