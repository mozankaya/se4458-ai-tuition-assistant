"""Concurrent Add Tuition calls, run on separate database connections that really commit.

These tests do not use the rolled-back `db_session` fixture: concurrency needs two transactions that
see each other's commits. They use student numbers that no other test uses and delete them afterwards.
"""

import threading
from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Student, Tuition
from app.schemas import TuitionUpsertRequest
from app.services.admin import process_batch_csv, upsert_tuition

ROUNDS = 10


@pytest.fixture
def cleanup(engine: Engine) -> Iterator[list[str]]:
    student_nos: list[str] = []
    yield student_nos
    with Session(engine) as session:
        ids = select(Student.id).where(Student.student_no.in_(student_nos))
        session.execute(delete(Tuition).where(Tuition.student_id.in_(ids)))
        session.execute(delete(Student).where(Student.student_no.in_(student_nos)))
        session.commit()


def _run_concurrently(engine: Engine, jobs: list[Callable[[Session], object]]) -> list[object]:
    """Start the jobs at the same moment, each in its own session; return results or raised exceptions."""
    barrier = threading.Barrier(len(jobs))
    results: list[object] = [None] * len(jobs)

    def worker(index: int, job: Callable[[Session], object]) -> None:
        with Session(engine) as session:
            barrier.wait()
            try:
                results[index] = job(session)
                session.commit()
            except Exception as exc:  # noqa: BLE001 - the test inspects what was raised
                session.rollback()
                results[index] = exc

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def _upsert(student_no: str, term: str, amount: str, currency: str = "USD") -> Callable[[Session], object]:
    request = TuitionUpsertRequest(student_no=student_no, term=term, amount=Decimal(amount), currency=currency)
    return lambda session: upsert_tuition(session, request)


def _count(engine: Engine, model, student_no: str) -> int:
    with Session(engine) as session:
        query = select(func.count()).select_from(model)
        if model is Tuition:
            query = query.join(Student)
        return session.scalar(query.where(Student.student_no == student_no))


def test_concurrent_creates_of_same_new_student_and_term(engine: Engine, cleanup: list[str]):
    for round_no in range(ROUNDS):
        student_no = f"2099{round_no:04d}"
        cleanup.append(student_no)

        results = _run_concurrently(engine, [_upsert(student_no, "2026-FALL", "1000"),
                                             _upsert(student_no, "2026-FALL", "2000")])

        # Neither request fails with a unique-constraint error: one creates, the other updates.
        assert sorted(r.status for r in results) == ["CREATED", "UPDATED"], results
        assert _count(engine, Student, student_no) == 1
        assert _count(engine, Tuition, student_no) == 1


def test_concurrent_creates_with_different_currencies_keep_one_currency(engine: Engine, cleanup: list[str]):
    for round_no in range(ROUNDS):
        student_no = f"2098{round_no:04d}"
        cleanup.append(student_no)

        results = _run_concurrently(engine, [_upsert(student_no, "2026-FALL", "1000", "USD"),
                                             _upsert(student_no, "2027-SPRING", "1000", "EUR")])

        # The student lock serializes the two calls, so the second one sees the first one's currency.
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1 and len(failures) == 1, results
        assert isinstance(failures[0], ApiError) and failures[0].code == "CURRENCY_MISMATCH"
        assert _count(engine, Tuition, student_no) == 1


def test_concurrent_batches_on_same_students_do_not_deadlock(engine: Engine, cleanup: list[str]):
    student_nos = [f"2097{i:04d}" for i in range(20)]
    cleanup.extend(student_nos)
    header = "studentNo,term,amount,currency\n"
    forward = header + "".join(f"{no},2026-FALL,100,USD\n" for no in student_nos)
    backward = header + "".join(f"{no},2026-FALL,200,USD\n" for no in reversed(student_nos))

    results = _run_concurrently(engine, [lambda s: process_batch_csv(s, forward.encode()),
                                         lambda s: process_batch_csv(s, backward.encode())])

    # Opposite row orders would deadlock if one batch held all its row locks until the end.
    assert all(not isinstance(r, Exception) for r in results), results
    assert [r.status for r in results] == ["COMPLETED", "COMPLETED"]
    assert sum(r.created_count for r in results) == len(student_nos)
    assert sum(r.updated_count for r in results) == len(student_nos)
    for no in student_nos:
        assert _count(engine, Tuition, no) == 1
