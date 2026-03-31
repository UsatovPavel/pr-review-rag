## Это прототип, если писать реальный то нужно начинать заново
## Аналоги:
SourceCraft/GitVerse отечественные - проект на Git храним, не хотим переезжать ради фичи
AI-review плагины для Github: Coderabbit и другие иностранные - не хотим передавать данные с непонятной политикой приватности.
Мотивация: хотим чтобы данные были приватными => не используем иностранные сервисы с непонятной политикой приватности.

Хотим не зависеть от провайдера модели: используем различные отечественные.
Итоги: накатал за 7 часов. Качество ревью неудовлетворительное.  LLM+RAG для ускорения ревью разработки RIID не подойдёт.

## Стек

- **Язык и окружение:** Python 3, локальный `.venv`, **Make** (`Makefile`) — `make install`, `make install-rag`, `make rag-review`, экспорт и GigaChat/Yandex-проверки.
- **Зависимости:** `httpx` (запросы к LLM), `python-dotenv` (`.env` / `.temp_env`); для RAG — `numpy`, `sentence-transformers` (через `requirements-rag.txt`, тянет PyTorch/transformers).
- **Git:** unified diff `merge-base..ветка` без checkout; путь к репозиторию кода — `GIT_REVIEW_REPO` или авто по `GITHUB_REPOSITORY` + `git remote origin` (`database/rag_review_branch/repo_resolve.py`).
- **RAG:** эмбеддинг текста diff + top-k по косинусной близости к чанкам в **SQLite** (BLOB эмбеддингов, напр. `review_rag_full.sqlite`); модель эмбеддингов по умолчанию — **sentence-transformers** `paraphrase-multilingual-MiniLM-L12-v2` (идентификатор в manifest после `rag-full`).
- **LLM:** **GigaChat** (Сбер, OAuth-токен) или **Yandex AI Studio** (OpenAI-compatible `.../v1/chat/completions`) — `providers/gigachat_review_chat.py`, `providers/yandex_review_chat.py`; переключение `RAG_REVIEW_LLM` / `--llm gigachat|yandex`.
- **Корпус и экспорт:** сборка индекса — `database/rag_full_pipeline.py` и связанные цели `make rag-full-*`; сырые данные — `retrieve_data/` (GitHub pulls, дерево коммитов, патчи), импорт чанков — `database/rag_sqlite_import.py`.

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
