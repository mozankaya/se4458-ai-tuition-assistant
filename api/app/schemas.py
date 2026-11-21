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


class TuitionSummary(CamelModel):
    """Overall totals for a student plus a per-term breakdown."""

    student_no: str = Field(examples=["20230001"])
    currency: str = Field(examples=["USD"])
    tuition_total: Money = Field(description="Sum of tuition over all terms")
    balance: Money = Field(description="Outstanding balance over all terms")
    terms: list[TermBalance]
