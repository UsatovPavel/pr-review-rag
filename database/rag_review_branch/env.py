"""Загрузка .env / .temp_env; корень репозитория pr-review-rag."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def sync_review_git_env_aliases() -> None:
    """
    Выравниваем ветку ревью с export: GIT_REVIEW_BRANCH ↔ GIT_LOG_REF (если задана только одна).
    Путь к клону кода — GIT_REVIEW_REPO / GITHUB_REPOSITORY+origin (см. repo_resolve).
    """
    log_ref = os.environ.get("GIT_LOG_REF", "").strip()
    review_branch = os.environ.get("GIT_REVIEW_BRANCH", "").strip()
    if review_branch and not log_ref:
        os.environ["GIT_LOG_REF"] = review_branch
    elif log_ref and not review_branch:
        os.environ["GIT_REVIEW_BRANCH"] = log_ref


def _repo_root() -> Path:
    # database/rag_review_branch/env.py → parents[2] = корень pr-review-rag
    return Path(__file__).resolve().parents[2]


def _load_env() -> None:
    """
    Сначала .env корня pr-review-rag (фиксированный путь к файлу), затем cwd — с override,
    чтобы при `make rag-review` из родительского клона (например Riid/) подтянулись GIT_* из pr-review-rag/.env.
    .temp_env поверх всего (токены).
    """
    root = _repo_root()
    load_dotenv(root / ".env")
    load_dotenv(Path.cwd() / ".env", override=True)
    load_dotenv(root / ".temp_env", override=True)
    load_dotenv(Path.cwd() / ".temp_env", override=True)
    sync_review_git_env_aliases()
