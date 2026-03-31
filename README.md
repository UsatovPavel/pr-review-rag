Аналоги: SourceCraft/GitVerse отечественные - проект на Git храним, не хотим переезжать ради фичи
AI-review плагины для Github: Coderabbit и другие иностранные - не хотим передавать данные с непонятной политикой приватности.
Мотивация: хотим чтобы данные были приватными => не используем иностранные сервисы с непонятной политикой приватности.

Хотим не зависеть от провайдера модели: используем различные отечественные.

Список ключей в окружении:
GITHUB_TOKEN
GITHUB_REPOSITORY
GIT_LOG_REF
SBER_CLIENT_ID
SBER_AUTH_KEY
SBER_SCOPE
YANDEX_AI_STUDIO_API_KEY
YANDEX_FOLDER_ID
RAG_REVIEW_LLM
GIT_REVIEW_REPO
GIT_REVIEW_BRANCH

GigaChat / MITM: если `make gigachat-token-insecure` и TLS к gigachat.devices падает на обычном `make rag-review`, добавьте в `.env` **`GIGACHAT_SSL_VERIFY=0`** (см. `.env.example`) или вызывайте **`make rag-review-insecure`**.

Ревью: по умолчанию **GigaChat** — **`GIGACHAT_MODEL`** или **`make rag-review-insecure ARGS='--model GigaChat-2-Max'`** (id из `make gigachat-ping-insecure`).

**Yandex AI Studio:** **`RAG_REVIEW_LLM=yandex`** и ключи **`YANDEX_AI_STUDIO_API_KEY`**, **`YANDEX_FOLDER_ID`**, либо **`make rag-review ARGS='--llm yandex --model yandexgpt-5-pro/latest'`** (см. `providers/yandex_review_chat.py`, `.env.example`).

**Ревью кода не из cwd:** **`GIT_REVIEW_REPO`** или **`GITHUB_REPOSITORY`** так, чтобы `origin` у кандидатного клона совпадал с `owner/repo`; ветка — **`GIT_LOG_REF`** (синхрон с **`GIT_REVIEW_BRANCH`**). См. `database/rag_review_branch/repo_resolve.py`, `env.py`, `.env.example`.