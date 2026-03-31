"""Парсинг unified diff (+строки) и проверка path:line в ответе модели."""

from __future__ import annotations

import re

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _normalize_diff_path(p: str) -> str:
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def unified_diff_added_lines(diff: str) -> set[tuple[str, int]]:
    """
    Множество (path, line) для строк новой версии, соответствующих '+' в hunks
    (номер строки в целевом файле после заголовка @@ ... +c,d @@).
    """
    result: set[tuple[str, int]] = set()
    lines = diff.splitlines()
    current_path: str | None = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("+++ "):
            raw = line[4:].strip().split("\t", 1)[0].strip()
            if raw == "/dev/null":
                current_path = None
            elif raw.startswith("b/"):
                current_path = _normalize_diff_path(raw[2:])
            else:
                current_path = _normalize_diff_path(raw)
            i += 1
            continue
        m = _HUNK_HEADER_RE.match(line)
        if m:
            cur_new = int(m.group(1))
            i += 1
            while i < n:
                hl = lines[i]
                if hl.startswith("@@") or hl.startswith("diff --git"):
                    break
                if hl.startswith("+++ ") or hl.startswith("--- "):
                    break
                if hl.startswith("\\"):
                    i += 1
                    continue
                if not hl:
                    i += 1
                    continue
                tag = hl[0]
                if tag == "+":
                    if current_path is not None:
                        result.add((current_path, cur_new))
                    cur_new += 1
                elif tag == " ":
                    cur_new += 1
                elif tag == "-":
                    pass
                else:
                    break
                i += 1
            continue
        i += 1
    return result


def _added_lines_normalized(diff: str) -> set[tuple[str, int]]:
    return {(_normalize_diff_path(p), ln) for p, ln in unified_diff_added_lines(diff)}


_REVIEW_ANCHOR_LINE = re.compile(
    r"^(\s*)(?:[-*+]\s+|\d+\.\s+)?(`?)([^\s:#`]+?):\s*(\d{1,7})\b",
    re.MULTILINE,
)


def _looks_like_file_path_token(path: str) -> bool:
    pl = path.lower()
    if pl.startswith(("http://", "https://")):
        return False
    if "/" in path:
        return True
    return bool(re.search(r"\.[A-Za-z0-9]{1,12}$", path))


def _resolve_ref_paths(ref: str, touched_norm: frozenset[str]) -> list[str]:
    """Сопоставить короткое имя или суффикс с путями из диффа."""
    refn = _normalize_diff_path(ref.strip("`"))
    if refn in touched_norm:
        return [refn]
    out: list[str] = []
    for p in touched_norm:
        if p == refn or p.endswith("/" + refn) or p.split("/")[-1] == refn:
            out.append(p)
    return list(dict.fromkeys(out))


def _invalid_path_line_anchors(
    answer: str,
    added: set[tuple[str, int]],
    touched_paths: list[str],
) -> list[str]:
    """Ссылки path:line в начале строки пункта, не попадающие в added (+ строки)."""
    path_keys = frozenset(p for p, _ in added)
    touched_norm = frozenset(_normalize_diff_path(p) for p in touched_paths)
    all_paths = touched_norm | path_keys
    bad: list[str] = []
    seen: set[tuple[str, int]] = set()
    for m in _REVIEW_ANCHOR_LINE.finditer(answer):
        raw_path = (m.group(3) or "").strip().strip("`")
        if not raw_path or not _looks_like_file_path_token(raw_path):
            continue
        try:
            ln = int(m.group(4))
        except ValueError:
            continue
        candidates = _resolve_ref_paths(raw_path, all_paths)
        if not candidates:
            candidates = [_normalize_diff_path(raw_path)]
        ok = any((_normalize_diff_path(cp), ln) in added for cp in candidates)
        key = (_normalize_diff_path(raw_path), ln)
        if not ok and key not in seen:
            seen.add(key)
            bad.append(f"`{raw_path}:{ln}`")
    return bad
