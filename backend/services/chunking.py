"""Split one page of pymupdf4llm markdown into heading-aware text chunks and whole tables."""
import re
from typing import Literal, TypedDict

from config import CHUNK_OVERLAP, MAX_CHUNK_CHARS

HEADING = re.compile(r"^#{1,6}\s+(.+)$")
CAPTION = re.compile(r"^[*_]*(table|tab\.)\s*[\dA-Z]", re.IGNORECASE)
NOISE = re.compile(r"[\d\s.\-–—|]*")  # bare page numbers, separators


class Chunk(TypedDict):
    type: Literal["text", "table"]
    text: str
    section: str | None


def _windows(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):  # prefer to break on whitespace
            cut = text.rfind(" ", start + max_chars - 300, end)
            end = cut if cut > start else end
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return out


def split_markdown(md: str, section: str | None = None,
                   max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        buf.clear()
        if text and not NOISE.fullmatch(text):
            chunks.extend({"type": "text", "text": w, "section": section}
                          for w in _windows(text, max_chars, overlap))

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            # pull a "Table N: ..." caption out of the text buffer
            caption = ""
            while buf and not buf[-1].strip():
                buf.pop()
            if buf and CAPTION.match(buf[-1].strip()):
                caption = buf.pop().strip() + "\n\n"
            flush()
            chunks.append({"type": "table", "text": caption + "\n".join(lines[i:j]), "section": section})
            i = j
            continue
        m = HEADING.match(line.strip())
        if m:
            flush()
            section = m.group(1).replace("*", "").replace("_", " ").strip()
        buf.append(line)
        i += 1
    flush()
    return chunks
