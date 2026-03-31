"""Дамп system/user в файл для отладки."""

from __future__ import annotations

from pathlib import Path


def write_debug_llm_request(
    out_path: Path,
    *,
    llm: str,
    model: str,
    temperature: float,
    chat_url: str,
    repo: Path,
    base_sha: str,
    base_note: str,
    upstream: str,
    embed_model: str,
    k: int,
    diff_chars: int,
    diff_truncated: bool,
    rag_section_chars: int,
    system_prompt: str,
    user_content: str,
    repo_resolution: str = "",
) -> None:
    """Полный текст system/user, уходит в API (секреты не пишем)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_lines = [
        "# LLM request dump (rag_review_branch)",
        "",
        f"- **llm:** `{llm}`",
        f"- **model:** `{model}`",
        f"- **temperature:** `{temperature}`",
        f"- **chat_url:** `{chat_url}`",
        f"- **repo:** `{repo}`",
        "",
    ]
    if repo_resolution.strip():
        meta_lines.extend(
            [
                repo_resolution.strip(),
                "",
            ]
        )
    meta_lines.extend(
        [
        f"- **base:** `{base_sha}` ({base_note})",
        f"- **upstream:** `{upstream}`",
        f"- **embed_model:** `{embed_model}`",
        f"- **top_k:** {k}",
        f"- **diff (in prompt) chars:** {diff_chars}",
        f"- **diff truncated:** {diff_truncated}",
        f"- **rag_section chars:** {rag_section_chars}",
        f"- **system chars:** {len(system_prompt)}",
        f"- **user chars (full message):** {len(user_content)}",
        "",
        "---",
        "",
        "## system",
        "",
        system_prompt,
        "",
        "---",
        "",
        "## user",
        "",
        user_content,
        "",
    ]
    )
    out_path.write_text("\n".join(meta_lines), encoding="utf-8")
