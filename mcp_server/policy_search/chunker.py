"""Split the policy Markdown document into one chunk per heading section."""

import re
from dataclasses import dataclass

# "## 3. Installment policy" or "### 3.2 Number and size of installments"
_HEADING = re.compile(r"^(#{2,3})\s+(?:(\d+(?:\.\d+)*)\.?\s+)?(.+?)\s*$")
_FENCE = re.compile(r"^\s*```")

INTRO_SECTION = "intro"


@dataclass(frozen=True)
class Chunk:
    section: str          # e.g. "3.2"; "intro" for text before the first "##" heading
    heading: str          # e.g. "Number and size of installments"
    parent_heading: str | None  # "##" heading that contains a "###" section
    text: str             # section body without the heading line

    @property
    def search_text(self) -> str:
        """Text used for indexing: headings are included so they also match queries."""
        return " ".join(part for part in (self.parent_heading, self.heading, self.text) if part)


def chunk_markdown(markdown: str, document_title: str = "Document overview") -> list[Chunk]:
    """Return one chunk per "##"/"###" section that has body text.

    Headings inside fenced code blocks are ignored. A "##" section whose only content is "###"
    subsections produces no chunk of its own; its title is kept as the subsections' parent_heading.
    """
    chunks: list[Chunk] = []
    section, heading, parent = INTRO_SECTION, document_title, None
    current_h2: str | None = None
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            chunks.append(Chunk(section=section, heading=heading, parent_heading=parent, text=text))

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match is None:
            body.append(line)
            continue

        flush()
        level, number, title = match.groups()
        body = []
        if level == "##":
            current_h2 = title
            section, heading, parent = number or title, title, None
        else:
            section, heading, parent = number or title, title, current_h2

    flush()
    return chunks
