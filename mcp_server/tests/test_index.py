from pathlib import Path

import pytest

from policy_search.chunker import Chunk
from policy_search.index import PolicyIndex, tokenize

POLICY_PATH = Path(__file__).resolve().parents[2] / "docs" / "University_Tuition_Policies.md"


@pytest.fixture(scope="module")
def index() -> PolicyIndex:
    return PolicyIndex.from_file(POLICY_PATH)


def _sections(index: PolicyIndex, query: str, top_k: int = 3) -> list[str]:
    return [m.section for m in index.search(query, top_k)]


# --- Retrieval quality on the real policy document (the three demo queries and more) ------------

def test_deadline_query_returns_deadline_sections(index: PolicyIndex):
    assert set(_sections(index, "When is the payment deadline?", 2)) == {"2.1", "2.2"}


def test_installment_query_returns_installment_policy(index: PolicyIndex):
    sections = _sections(index, "Can I pay my outstanding balance in installments?")

    assert sections[0] == "3.1"
    assert "8.2" in sections


def test_late_fee_query_returns_late_fee_rule(index: PolicyIndex):
    assert set(_sections(index, "Is there a late fee?", 2)) == {"4.1", "4.2"}


def test_refund_query_returns_refund_sections(index: PolicyIndex):
    assert set(_sections(index, "refund after withdrawal")) == {"6.1", "6.2", "6.3"}


def test_automatic_payment_query_returns_confirmation_rule(index: PolicyIndex):
    assert _sections(index, "Can the assistant pay my tuition automatically?")[0] == "8.4"


# --- Search behaviour ----------------------------------------------------------------------------

def test_response_matches_policy_section_9_format(index: PolicyIndex):
    response = index.search_response("installments", top_k=1)

    assert response["document"] == "University_Tuition_Policies.md"
    assert len(response["matches"]) == 1
    match = response["matches"][0]
    assert set(match) == {"section", "heading", "text", "score"}
    assert match["score"] > 0


def test_results_are_sorted_by_score(index: PolicyIndex):
    scores = [m.score for m in index.search("payment balance", top_k=10)]

    assert scores == sorted(scores, reverse=True)
    assert len(scores) == 10


def test_unrelated_query_returns_no_matches(index: PolicyIndex):
    assert index.search("xyzzy quantum banana") == []


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_is_rejected(index: PolicyIndex, query: str):
    with pytest.raises(ValueError):
        index.search(query)


@pytest.mark.parametrize("top_k", [0, 11])
def test_top_k_out_of_range_is_rejected(index: PolicyIndex, top_k: int):
    with pytest.raises(ValueError):
        index.search("deadline", top_k=top_k)


def test_index_is_built_once_and_does_not_reread_the_file(tmp_path: Path):
    copy = tmp_path / "policy.md"
    copy.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    index = PolicyIndex.from_file(copy)

    copy.unlink()

    assert index.search("deadline")  # still answers from memory


def test_index_requires_chunks():
    with pytest.raises(ValueError):
        PolicyIndex([], document="empty.md")


def test_small_index_ranks_relevant_chunk_first():
    chunks = [
        Chunk("1", "Deadlines", None, "Pay before the deadline."),
        Chunk("2", "Refunds", None, "Refunds take 15 business days."),
        Chunk("3", "Contact", None, "Email the finance office."),
    ]

    assert [m.section for m in PolicyIndex(chunks, "x.md").search("refunds", top_k=3)] == ["2"]


# --- Tokenizer -----------------------------------------------------------------------------------

def test_tokenize_lowercases_drops_stopwords_and_plural_s():
    assert tokenize("What are the Late Fees for installments?") == ["late", "fee", "installment"]


def test_tokenize_keeps_numbers_and_short_words():
    assert tokenize("2% fee on $300 is due") == ["2", "fee", "300", "due"]
