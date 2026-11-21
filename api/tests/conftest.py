"""Shared fixtures. Tests run against the separate `db-test` PostgreSQL container."""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app
from app.seed import seed

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


@pytest.fixture
def seeded(db_session: Session) -> Session:
    """Test session pre-loaded with the demo seed data."""
    seed(db_session, TEST_DEMO_PASSWORD)
    return db_session


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """API client whose requests use the per-test database session."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def login(client: TestClient) -> Callable[[str], dict[str, str]]:
    """Return a helper that logs in a demo user and returns Authorization headers."""

    def _login(username: str) -> dict[str, str]:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": TEST_DEMO_PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
