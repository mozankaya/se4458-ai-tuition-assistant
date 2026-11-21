"""In-memory BM25 index over policy chunks. Built once at startup, then queried many times."""

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from policy_search.chunker import Chunk, chunk_markdown

MAX_TOP_K = 10

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its my of on or "
    "the this that to was what when where which who will with you your".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords; a trailing plural "s" is removed (fees -> fee)."""
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


@dataclass(frozen=True)
class Match:
    section: str
    heading: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return {"section": self.section, "heading": self.heading, "text": self.text, "score": self.score}


class PolicyIndex:
    def __init__(self, chunks: list[Chunk], document: str) -> None:
        if not chunks:
            raise ValueError("Cannot build an index without chunks")
        self.document = document
        self.chunks = chunks
        self._bm25 = BM25Okapi([tokenize(chunk.search_text) for chunk in chunks])

    @classmethod
    def from_file(cls, path: str | Path) -> "PolicyIndex":
        path = Path(path)
        markdown = path.read_text(encoding="utf-8")
        title = next((line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), path.stem)
        return cls(chunk_markdown(markdown, document_title=title), document=path.name)

    def search(self, query: str, top_k: int = 3) -> list[Match]:
        """Return up to top_k chunks with a positive BM25 score, best first."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")

        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        return [
            Match(
                section=self.chunks[i].section,
                heading=self.chunks[i].heading,
                text=self.chunks[i].text,
                score=round(float(scores[i]), 4),
            )
            for i in ranked[:top_k]
            if scores[i] > 0
        ]

    def search_response(self, query: str, top_k: int = 3) -> dict:
        """Response shape from section 9 of the policy document."""
        return {"document": self.document, "matches": [m.to_dict() for m in self.search(query, top_k)]}
