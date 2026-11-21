"""Bounded, deterministic excerpts that the model can cite without rewriting."""

import re
import unicodedata


EVIDENCE_VERSION = 1
EXCERPT_WORDS = 10
MAX_EXCERPT_CHARS = 240
MAX_EXCERPTS = 32


def excerpt_catalog(source: dict, focus: str = "") -> list[dict]:
    """Select exact normalized spans, preferring windows near focus matches."""
    terms = set(re.findall(r"[\w.-]{3,}", focus.casefold()))
    candidates = []
    for page_index, passage in enumerate(source["passages"]):
        text = " ".join(unicodedata.normalize("NFKC", passage["text"]).split())
        words = list(re.finditer(r"\S+", text))
        if not words:
            continue
        hits = [match.start() for term in terms for match in re.finditer(re.escape(term), text.casefold())]
        last = max(0, len(words) - EXCERPT_WORDS)
        starts = sorted({*range(0, last + 1, EXCERPT_WORDS // 2), last})
        minimum = min(12, len(text)) if source["kind"] == "question" else 12
        for start in starts:
            left = words[start].start()
            right = words[min(start + EXCERPT_WORDS, len(words)) - 1].end()
            quote = text[left:right]
            if not minimum <= len(quote) <= MAX_EXCERPT_CHARS:
                continue
            distance = min((max(left - hit, hit - right, 0) for hit in hits), default=0)
            rank = (0 if hits or not terms else 1, distance, page_index, start)
            candidates.append((rank, page_index, start, passage["page"], quote))
    chosen, seen = [], set()
    for item in sorted(candidates):
        key = (item[3], item[4])
        if key not in seen:
            chosen.append(item)
            seen.add(key)
        if len(chosen) >= MAX_EXCERPTS:
            break
    return [{"excerpt_id": f"{source['source_id']}-E{index}", "text": item[4], "page": item[3]}
            for index, item in enumerate(chosen, 1)]
