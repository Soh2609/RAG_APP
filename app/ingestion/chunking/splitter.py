import re
from typing import List
import logfire


def _split_oversized_text(text: str, max_size: int, overlap: int) -> List[str]:
    """Recursively splits text that exceeds max_size by sentence, newline, or word boundaries

    while maintaining context overlap.
    """
    if len(text) <= max_size:
        return [text.strip()] if text.strip() else []

    # Priority separators: sentence ends, newlines, spaces
    separators = [r"(?<=[.!?])\s+", r"\n+", r"\s+"]
    for sep in separators:
        parts = re.split(sep, text)
        if len(parts) > 1:
            chunks: List[str] = []
            current = ""
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if len(current) + len(part) + 1 <= max_size:
                    current = f"{current} {part}".strip()
                else:
                    if current:
                        chunks.append(current)
                        # Carry overlap from the end of the previous chunk
                        overlap_tail = current[-overlap:].strip() if overlap > 0 else ""
                        current = f"{overlap_tail} {part}".strip()
                    else:
                        # Single part itself exceeds max_size, slice by char window
                        for i in range(0, len(part), max_size - overlap):
                            sub = part[i : i + max_size].strip()
                            if sub:
                                chunks.append(sub)
                        current = ""
            if current:
                chunks.append(current)
            return [c for c in chunks if c]

    # Fallback hard slice if no separator matched
    hard_chunks = []
    step = max(1, max_size - overlap)
    for i in range(0, len(text), step):
        slice_part = text[i : i + max_size].strip()
        if slice_part:
            hard_chunks.append(slice_part)
    return hard_chunks


def chunk_text(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> List[str]:
    """Semantic-aware text chunker.

    Splits primarily on paragraph boundaries (double newlines), with recursive sub-splitting
    for oversized sections, and maintains configurable context overlap across chunks.
    """
    with logfire.span("Text chunking", text_length=len(text), chunk_size=chunk_size, overlap=chunk_overlap):
        if not text or not text.strip():
            return []

        raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: List[str] = []
        current_chunk = ""

        for p in raw_paragraphs:
            # If paragraph itself is oversized, break it down first
            if len(p) > chunk_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                sub_chunks = _split_oversized_text(p, chunk_size, chunk_overlap)
                chunks.extend(sub_chunks)
                continue

            candidate = f"{current_chunk}\n\n{p}".strip() if current_chunk else p
            if len(candidate) <= chunk_size:
                current_chunk = candidate
            else:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    # Add overlap from current_chunk if applicable
                    overlap_tail = current_chunk[-chunk_overlap:].strip() if chunk_overlap > 0 else ""
                    current_chunk = f"{overlap_tail}\n\n{p}".strip() if overlap_tail else p
                else:
                    current_chunk = p

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # Clean, deduplicate immediate duplicates, and filter
        valid_chunks: List[str] = []
        for c in chunks:
            c_clean = c.strip()
            if c_clean and (not valid_chunks or valid_chunks[-1] != c_clean):
                valid_chunks.append(c_clean)

        logfire.info(f"Generated {len(valid_chunks)} chunks from {len(text)} characters")
        return valid_chunks
