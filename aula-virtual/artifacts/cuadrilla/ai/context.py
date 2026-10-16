"""Small lexical RAG, with bounded context and no external/vector database."""

import re


def chunks_for(text: str, size: int = 2400, overlap: int = 240) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.casefold()) if len(word) > 3}


def select_context(text: str, query: str = "", limit: int = 8) -> str:
    chunks = chunks_for(text)
    if len(chunks) <= limit:
        selected = range(len(chunks))
    elif query:
        terms = tokens(query)
        selected = sorted(sorted(range(len(chunks)), key=lambda i: len(terms & tokens(chunks[i])), reverse=True)[:limit])
    else:
        # Uniform coverage keeps beginnings, middle and endings, instead of truncating.
        selected = sorted({round(i * (len(chunks) - 1) / (limit - 1)) for i in range(limit)})
    return "\n\n".join(f"[Fragmento {i + 1}]\n{chunks[i]}" for i in selected)
