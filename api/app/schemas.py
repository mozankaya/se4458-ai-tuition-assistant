"""Shared Pydantic schemas. Public JSON uses camelCase field names (e.g. studentNo)."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

# Money is kept as Decimal internally and rendered as a JSON number with 2 decimals.
Money = Annotated[Decimal, PlainSerializer(lambda value: float(value), return_type=float, when_used="json")]

STUDENT_NO_PATTERN = r"^[0-9]{1,20}$"
TERM_PATTERN = r"^[0-9]{4}-(FALL|SPRING|SUMMER)$"


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TermBalance(CamelModel):
    term: str = Field(examples=["2026-FALL"])
    tuition_total: Money
    paid_amount: Money
    balance: Money


class PaymentRequest(CamelModel):
    student_no: str = Field(pattern=STUDENT_NO_PATTERN, examples=["20230001"])
    term: str = Field(pattern=TERM_PATTERN, examples=["2026-FALL"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=[500.00])
    transaction_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Client-generated unique ID (e.g. UUID). Reused IDs are rejected.",
        examples=["3f1c2a9e-8d7b-4c1e-9a55-0b6f1e2d4c3a"],
    )


class PaymentResponse(CamelModel):
    status: str = Field(examples=["SUCCESS"])
    transaction_id: str
    student_no: str
    term: str
    paid_amount: Money = Field(description="Amount recorded by this payment")
    remaining_balance: Money = Field(description="Outstanding balance for the term after this payment")
    currency: str


class TuitionUpsertRequest(CamelModel):
    student_no: str = Field(pattern=STUDENT_NO_PATTERN, examples=["20230006"])
    term: str = Field(pattern=TERM_PATTERN, examples=["2026-FALL"])
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2, examples=[3000.00])
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$", examples=["USD"])


class TuitionUpsertResponse(CamelModel):
    status: str = Field(description="CREATED or UPDATED", examples=["CREATED"])
    student_no: str
    term: str
    amount: Money
    paid_amount: Money
    balance: Money
    currency: str


class BatchRowError(CamelModel):
    line: int = Field(description="Line number in the CSV file (header is line 1)")
    student_no: str | None
    term: str | None
    code: str
    message: str


class BatchResult(CamelModel):
    status: str = Field(description="COMPLETED, PARTIAL or FAILED", examples=["PARTIAL"])
    total_rows: int
    success_count: int
    failure_count: int
    created_count: int
    updated_count: int
    errors: list[BatchRowError]


class UnpaidTuitionItem(CamelModel):
    student_no: str
    full_name: str | None
    term: str
    tuition_total: Money
    paid_amount: Money
    balance: Money
    currency: str


class UnpaidTuitionPage(CamelModel):
    term: str | None = Field(description="Term filter, or null for all terms")
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: list[UnpaidTuitionItem]


class TuitionSummary(CamelModel):
    """Overall totals for a student plus a per-term breakdown."""

    student_no: str = Field(examples=["20230001"])
    currency: str = Field(examples=["USD"])
    tuition_total: Money = Field(description="Sum of tuition over all terms")
    balance: Money = Field(description="Outstanding balance over all terms")
    terms: list[TermBalance]
