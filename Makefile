# POSIX Make + sh (Git Bash / WSL / Linux / macOS). On Windows use Git Bash or WSL for `make`.

PYTHON ?= python

ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python.exe
  PIP := .venv/Scripts/pip.exe
else
  PY := .venv/bin/python
  PIP := .venv/bin/pip
endif

.PHONY: help venv install export-pulls export-github export-git-history-tree export-commit-diffs

.DEFAULT_GOAL := help


venv:
	$(PYTHON) -m venv .venv

install: venv
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt

# Uses GITHUB_REPOSITORY, GITHUB_TOKEN (or GH_TOKEN) from the environment.
# Optional: make export-pulls ARGS="owner/repo" or ARGS="--state open owner/repo"
export-pulls:
	$(PY) export_pulls.py $(ARGS)

export-github:
	$(PY) github_pulls.py $(ARGS)

export-git-history-tree:
	$(PY) git_history_tree_export.py $(ARGS)

export-commit-diffs:
	$(PY) export_commit_diffs.py $(ARGS)

help:
	@echo Targets:
	@echo "  make install          - venv + pip install -r requirements.txt"
	@echo "  make export-pulls     - GitHub + optional git history tree (export_pulls.py)"
	@echo "  make export-github    - only GitHub (github_pulls.py)"
	@echo "  make export-git-history-tree - export/git_history_tree.jsonl"
	@echo "  make export-commit-diffs - all commits: git rev-list --all + .patch per sha"
	@echo "  history tree: GIT_HISTORY_TREE_OUT, GIT_LOG_REF -> on_ref, GIT_LOG_MAX=0 unlimited"