"""Shared fixtures. Tests run against the separate `db-test` PostgreSQL container."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.config import get_settings
from app.db import Base

TEST_DEMO_PASSWORD = "test-password"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = get_settings().test_database_url
    if not url:
        pytest.exit("TEST_DATABASE_URL is not configured (see .env.example)", returncode=1)
    test_engine = create_engine(url)
    try:
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.exit("Test database is not reachable. Run: docker compose up -d db-test", returncode=1)

    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """Session wrapped in an outer transaction that is rolled back after each test.

    Commits inside the test only release a SAVEPOINT, so tests stay isolated.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()
