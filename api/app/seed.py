"""Create the schema and load demo data.

Usage (from the api/ directory):
    python -m app.seed           # create tables if missing, insert missing demo rows
    python -m app.seed --reset   # drop all tables, recreate and seed

Demo users share the password from SEED_DEMO_PASSWORD (see .env.example).
"""

import argparse
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.config import get_settings
from app.db import Base, get_engine
from app.models import ROLE_ADMIN, ROLE_BANK, ROLE_STUDENT, Payment, Student, Tuition, User
from app.security import hash_password

# (student_no, full_name, email, [(term, amount, paid_amount)])
DEMO_STUDENTS = [
    # Large unpaid balance in two terms: eligible to request installments (balance >= $300).
    ("20230001", "Alex Morgan", "alex.morgan@uni.example", [("2026-FALL", "3000.00", "0.00"),
                                                             ("2027-SPRING", "3000.00", "0.00")]),
    # Merit scholarship (25% off 3000): Fall fully paid, Spring partially paid.
    ("20230002", "Jamie Lee", "jamie.lee@uni.example", [("2026-FALL", "2250.00", "2250.00"),
                                                         ("2027-SPRING", "2250.00", "1000.00")]),
    # Small balance below the $300 installment threshold.
    ("20230003", "Taylor Kim", "taylor.kim@uni.example", [("2026-FALL", "250.00", "0.00")]),
    # Half paid Fall term.
    ("20230004", "Jordan Smith", "jordan.smith@uni.example", [("2026-FALL", "3000.00", "1500.00")]),
    # Student with no tuition record yet.
    ("20230005", "Casey Brown", "casey.brown@uni.example", []),
]

# (username, role, student_no or None)
DEMO_USERS = [
    ("student1", ROLE_STUDENT, "20230001"),
    ("student2", ROLE_STUDENT, "20230002"),
    ("student3", ROLE_STUDENT, "20230003"),
    ("student4", ROLE_STUDENT, "20230004"),
    ("bank1", ROLE_BANK, None),
    ("admin1", ROLE_ADMIN, None),
]


def create_schema(engine: Engine, reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed(session: Session, demo_password: str) -> dict[str, int]:
    """Insert demo rows that do not exist yet. Safe to run repeatedly."""
    if not demo_password:
        raise RuntimeError("SEED_DEMO_PASSWORD is not configured")

    created = {"students": 0, "tuitions": 0, "payments": 0, "users": 0}
    students: dict[str, Student] = {}

    for student_no, full_name, email, tuitions in DEMO_STUDENTS:
        student = session.scalar(select(Student).where(Student.student_no == student_no))
        if student is None:
            student = Student(student_no=student_no, full_name=full_name, email=email)
            session.add(student)
            session.flush()
            created["students"] += 1
        students[student_no] = student

        for term, amount, paid in tuitions:
            exists = session.scalar(
                select(Tuition).where(Tuition.student_id == student.id, Tuition.term == term)
            )
            if exists is not None:
                continue
            tuition = Tuition(
                student_id=student.id,
                term=term,
                amount=Decimal(amount),
                paid_amount=Decimal(paid),
                currency="USD",
            )
            session.add(tuition)
            session.flush()
            created["tuitions"] += 1
            if Decimal(paid) > 0:
                session.add(
                    Payment(
                        transaction_id=f"seed-{student_no}-{term}",
                        tuition_id=tuition.id,
                        amount=Decimal(paid),
                        channel="banking",
                    )
                )
                created["payments"] += 1

    password_hash = hash_password(demo_password)
    for username, role, student_no in DEMO_USERS:
        if session.scalar(select(User).where(User.username == username)) is not None:
            continue
        session.add(
            User(
                username=username,
                password_hash=password_hash,
                role=role,
                student_id=students[student_no].id if student_no else None,
            )
        )
        created["users"] += 1

    session.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Create schema and load demo data.")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()

    engine = get_engine()
    create_schema(engine, reset=args.reset)
    with Session(engine) as session:
        created = seed(session, get_settings().seed_demo_password)
    print(f"Seed complete: {created}")


if __name__ == "__main__":
    main()
