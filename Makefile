# POSIX Make + sh (Git Bash / WSL / Linux / macOS). On Windows use Git Bash or WSL for `make`.

PYTHON ?= python
# Large (torch/transformers); raise if downloads time out on slow links
PIP_TIMEOUT ?= 30

ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python.exe
  PIP := .venv/Scripts/pip.exe
else
  PY := .venv/bin/python
  PIP := .venv/bin/pip
endif

.PHONY: help venv install install-rag install-yandex yandex-check rag-sqlite-import rag-full-corpus rag-full-embed rag-full-sqlite rag-full rag-review rag-review-insecure export-pulls export-github export-git-history-tree export-commit-diffs gigachat-token gigachat-token-insecure gigachat-ping gigachat-ping-insecure rag-embed-local

.DEFAULT_GOAL := help


venv:
	$(PYTHON) -m venv .venv

install: venv
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt

# PyTorch + sentence-transformers for local_rag_embeddings.py
install-rag: venv
	$(PIP) install -U pip
	$(PIP) install --default-timeout=$(PIP_TIMEOUT) --retries 10 -r requirements-rag.txt

# yandex_ai_studio_check.py (YANDEX_AI_STUDIO_API_KEY + YANDEX_FOLDER_ID in .env)
install-yandex: venv
	$(PIP) install -U pip
	$(PIP) install -r requirements-yandex.txt

yandex-check:
	$(PY) providers/yandex_ai_studio_check.py $(ARGS)

rag-embed-local:
	$(PY) providers/local_rag_embeddings.py $(ARGS)

# review_rag.sqlite: chunks (id, source, text, meta JSON, embedding BLOB). ARGS e.g. --replace --embeddings
rag-sqlite-import:
	$(PY) database/rag_sqlite_import.py $(ARGS)

# Full corpus: export/* → rag_corpus.jsonl → rag_full_embed → review_rag_full.sqlite (не трогает local_rag_embeddings.py)
rag-full-corpus:
	$(PY) database/rag_full_pipeline.py corpus $(ARGS)

rag-full-embed:
	$(PY) database/rag_full_pipeline.py embed $(ARGS)

rag-full-sqlite:
	$(PY) database/rag_full_pipeline.py sqlite $(ARGS)

rag-full:
	$(PY) database/rag_full_pipeline.py all $(ARGS)

# git diff + RAG + LLM → review.md. ARGS e.g. --llm yandex --model yandexgpt-5-pro/latest; MITM: rag-review-insecure
rag-review:
	$(PY) database/rag_review_branch.py $(ARGS)

# Same as rag-review with GIGACHAT_SSL_VERIFY=0 (corporate proxy / broken chain)
rag-review-insecure:
	env GIGACHAT_SSL_VERIFY=0 $(PY) database/rag_review_branch.py $(ARGS)

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

# OAuth: SBER_AUTH_KEY; optional GIGACHAT_SCOPE. TLS: GIGACHAT_SSL_VERIFY=0 (dev) or GIGACHAT_CA_BUNDLE=path.pem
gigachat-token:
	$(PY) providers/gigachat_oauth.py $(ARGS)

# Same as gigachat-token but skips TLS verify (corporate proxy / missing CA). Insecure.
gigachat-token-insecure:
	env GIGACHAT_SSL_VERIFY=0 $(PY) providers/gigachat_oauth.py $(ARGS)

# GET /api/v1/models — проверка токена (истёк ~30 мин → 401)
gigachat-ping:
	$(PY) providers/gigachat_ping.py $(ARGS)

gigachat-ping-insecure:
	env GIGACHAT_SSL_VERIFY=0 $(PY) providers/gigachat_ping.py $(ARGS)

help:
	@echo Targets:
	@echo "  make install          - venv + pip install -r requirements.txt"
	@echo "  make install-rag      - RAG deps (slow download); PIP_TIMEOUT=600 make install-rag if timeouts"
	@echo "  make install-yandex   - AI Studio SDK for yandex-check"
	@echo "  make yandex-check     - test YANDEX_AI_STUDIO_API_KEY + folder id (.env)"
	@echo "  make rag-embed-local  - export/rag_embed from export/pr_comments.jsonl"
	@echo "  make rag-sqlite-import - review_rag.sqlite from JSONL (+ optional embeddings.npy)"
	@echo "  make rag-full-corpus  - export/rag_corpus.jsonl (PR comments + pulls + git tree + patches)"
	@echo "  make rag-full-embed   - export/rag_full_embed (sentence-transformers)"
	@echo "  make rag-full-sqlite  - review_rag_full.sqlite from corpus + embeddings"
	@echo "  make rag-full         - corpus + embed + sqlite (ARGS e.g. --replace)"
	@echo "  make rag-review       - diff + RAG + LLM (ARGS: --llm gigachat|yandex, --model ...)"
	@echo "  make rag-review-insecure - rag-review if TLS fails (GIGACHAT_SSL_VERIFY=0)"
	@echo "  make export-pulls     - GitHub + optional git history tree (export_pulls.py)"
	@echo "  make export-github    - only GitHub (github_pulls.py)"
	@echo "  make export-git-history-tree - export/git_history_tree.jsonl"
	@echo "  make export-commit-diffs - all commits: git rev-list --all + .patch per sha"
	@echo "  make gigachat-token   - GigaChat OAuth -> .temp_env (SBER_AUTH_KEY in .env)"
	@echo "  make gigachat-token-insecure - if curl/python fail with SSL (MITM); or .env GIGACHAT_SSL_VERIFY=0"
	@echo "  make gigachat-ping        - GET models (debug token); gigachat-ping-insecure if TLS fails"
	@echo "  history tree: GIT_HISTORY_TREE_OUT, GIT_LOG_REF -> on_ref, GIT_LOG_MAX=0 unlimited"