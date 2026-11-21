"""SQLAlchemy ORM models. See docs/er-diagram.md for the ER diagram."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MONEY = Numeric(12, 2)

ROLE_STUDENT = "student"
ROLE_BANK = "bank"
ROLE_ADMIN = "admin"
ROLES = (ROLE_STUDENT, ROLE_BANK, ROLE_ADMIN)

TERM_PATTERN = r"^[0-9]{4}-(FALL|SPRING|SUMMER)$"


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tuitions: Mapped[list["Tuition"]] = relationship(back_populates="student", order_by="Tuition.term")
    user: Mapped["User | None"] = relationship(back_populates="student")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="ck_users_role"),
        CheckConstraint(
            "(role = 'student') = (student_id IS NOT NULL)",
            name="ck_users_student_link",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10))
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student | None] = relationship(back_populates="user")


class Tuition(Base):
    __tablename__ = "tuitions"
    __table_args__ = (
        UniqueConstraint("student_id", "term", name="uq_tuitions_student_term"),
        CheckConstraint("amount >= 0", name="ck_tuitions_amount_non_negative"),
        CheckConstraint("paid_amount >= 0 AND paid_amount <= amount", name="ck_tuitions_paid_range"),
        CheckConstraint(f"term ~ '{TERM_PATTERN}'", name="ck_tuitions_term_format"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_tuitions_currency_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    term: Mapped[str] = mapped_column(String(20), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="tuitions")
    payments: Mapped[list["Payment"]] = relationship(back_populates="tuition")

    @property
    def balance(self) -> Decimal:
        return self.amount - self.paid_amount


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("status IN ('SUCCESS')", name="ck_payments_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tuition_id: Mapped[int] = mapped_column(ForeignKey("tuitions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    channel: Mapped[str] = mapped_column(String(20), default="banking")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tuition: Mapped[Tuition] = relationship(back_populates="payments")


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    # student_no is intentionally not a foreign key: unknown numbers are limited too.
    student_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(50), primary_key=True)
    window_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
