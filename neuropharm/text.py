from __future__ import annotations

import html
import re


def clean_text(text: str | None) -> str:
    if not text:
        return ""

    cleaned = html.unescape(str(text))
    cleaned = re.sub(r"<\s*br\s*/?\s*>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*(sub|sup)\s*>(.*?)<\s*/\s*\1\s*>", r"\2", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?\s*(sub|sup)\s*>?", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    cleaned = re.sub(r"\s+\*\s+", " ", cleaned)

    def clean_reference(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        citation = r"(?:label|fda label|[A-Z]\d+|DB\d+)"
        if re.fullmatch(fr"{citation}(?:\s*,\s*{citation})*", inner, flags=re.IGNORECASE):
            return ""
        return inner

    cleaned = re.sub(r"\[([^\[\]]+)\]", clean_reference, cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def compact(text: str | None, limit: int = 500) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "..."
