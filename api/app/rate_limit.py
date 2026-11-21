"""Daily per-student request counter stored in PostgreSQL."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RateLimitCounter


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    count: int
    retry_after_seconds: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.count, 0)


def local_now() -> datetime:
    """Current time in the university time zone. Overridden in tests."""
    return datetime.now(ZoneInfo(get_settings().app_timezone))


def _seconds_until_next_day(now: datetime) -> int:
    next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo)
    return max(int((next_midnight - now).total_seconds()), 1)


def consume(db: Session, student_no: str, endpoint: str, limit: int, now: datetime) -> RateLimitResult:
    """Atomically count one request for (student_no, endpoint, today) and commit it.

    The counter is committed immediately so it survives even if the request later fails (e.g. 404).
    """
    window: date = now.date()
    stmt = (
        insert(RateLimitCounter)
        .values(student_no=student_no, endpoint=endpoint, window_date=window, request_count=1)
        .on_conflict_do_update(
            index_elements=["student_no", "endpoint", "window_date"],
            set_={"request_count": RateLimitCounter.request_count + 1},
        )
        .returning(RateLimitCounter.request_count)
    )
    count = db.execute(stmt).scalar_one()
    db.commit()
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        count=count,
        retry_after_seconds=_seconds_until_next_day(now),
    )
