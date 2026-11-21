from pathlib import Path

from policy_search.chunker import INTRO_SECTION, chunk_markdown

POLICY_PATH = Path(__file__).resolve().parents[2] / "docs" / "University_Tuition_Policies.md"

SAMPLE = """# Sample Policy

Intro paragraph.

## 1. Scope

Scope text.

## 2. Deadlines

### 2.1 Fall term

Fall text.

```json
## not a heading
```

### 2.2 Spring term

Spring text.

## Appendix

Appendix text.
"""


def test_sample_document_is_split_per_section():
    chunks = chunk_markdown(SAMPLE, document_title="Sample Policy")

    assert [(c.section, c.heading, c.parent_heading) for c in chunks] == [
        (INTRO_SECTION, "Sample Policy", None),
        ("1", "Scope", None),
        ("2.1", "Fall term", "Deadlines"),
        ("2.2", "Spring term", "Deadlines"),
        ("Appendix", "Appendix", None),
    ]


def test_heading_only_section_produces_no_chunk():
    sections = [c.section for c in chunk_markdown(SAMPLE)]

    assert "2" not in sections


def test_headings_inside_code_fences_are_kept_as_text():
    fall = next(c for c in chunk_markdown(SAMPLE) if c.section == "2.1")

    assert "## not a heading" in fall.text
    assert fall.text.startswith("Fall text.")


def test_search_text_includes_parent_and_heading():
    fall = next(c for c in chunk_markdown(SAMPLE) if c.section == "2.1")

    assert fall.search_text.startswith("Deadlines Fall term Fall text.")


def test_policy_document_chunks_cover_every_numbered_subsection():
    chunks = chunk_markdown(POLICY_PATH.read_text(encoding="utf-8"))
    sections = [c.section for c in chunks]

    assert sections == [
        "intro", "1", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "3.4", "4.1", "4.2", "4.3",
        "5.1", "5.2", "6.1", "6.2", "6.3", "7.1", "7.2", "7.3", "7.4", "8.1", "8.2", "8.3", "8.4", "9",
    ]
    assert all(c.text for c in chunks)
    installments = next(c for c in chunks if c.section == "3.2")
    assert installments.heading == "Number and size of installments"
    assert installments.parent_heading == "Installment policy"
    assert "up to three installments" in installments.text
