# Data Model (ER Diagram)

The Tuition REST API stores live account data in PostgreSQL. The policy document is **not** part of this
database; it is indexed separately by the MCP server.

```mermaid
erDiagram
    STUDENTS ||--o{ TUITIONS : "is billed"
    STUDENTS |o--o| USERS : "logs in as"
    TUITIONS ||--o{ PAYMENTS : "is paid by"
    USERS |o--o{ PAYMENTS : "submits"

    STUDENTS {
        int id PK
        varchar student_no UK "e.g. 20230001"
        varchar full_name "nullable"
        varchar email "nullable"
        timestamptz created_at
    }

    USERS {
        int id PK
        varchar username UK
        varchar password_hash
        varchar role "student | bank | admin"
        int student_id FK "UK, required only for role student"
        boolean is_active
        timestamptz created_at
    }

    TUITIONS {
        int id PK
        int student_id FK
        varchar term "e.g. 2026-FALL"
        numeric amount "NUMERIC(12,2), >= 0"
        numeric paid_amount "NUMERIC(12,2), 0 <= paid_amount <= amount"
        char currency "ISO 4217, default USD"
        timestamptz created_at
        timestamptz updated_at
    }

    PAYMENTS {
        int id PK
        varchar transaction_id UK "client idempotency key"
        int tuition_id FK
        int user_id FK "nullable, who submitted"
        numeric amount "NUMERIC(12,2), > 0"
        varchar status "SUCCESS"
        varchar channel "banking | agent"
        timestamptz created_at
    }

    RATE_LIMIT_COUNTERS {
        varchar student_no PK "not a FK: unknown numbers are counted too"
        varchar endpoint PK "e.g. mobile_tuition_query"
        date window_date PK "calendar day in Europe/Istanbul"
        int request_count
    }
```

## Tables

| Table | Purpose | Key constraints |
|---|---|---|
| `students` | Student identity | `student_no` unique |
| `users` | Login accounts for the demo roles | `username` unique; `role IN ('student','bank','admin')`; `student_id` unique and `NOT NULL` when `role = 'student'`, `NULL` otherwise |
| `tuitions` | Assessed tuition per student and term | `UNIQUE (student_id, term)`; `amount >= 0`; `0 <= paid_amount <= amount` |
| `payments` | Immutable payment ledger | `transaction_id` unique (duplicate submissions are rejected); `amount > 0` |
| `rate_limit_counters` | Daily counter for the mobile query limit | Composite PK `(student_no, endpoint, window_date)`; incremented atomically with `INSERT ... ON CONFLICT DO UPDATE` |

## Derived values

- **Term balance** = `tuitions.amount - tuitions.paid_amount`.
- **Overall tuition total / balance** = sums over all of a student's `tuitions` rows.
- `tuitions.paid_amount` is a running total kept in sync with `payments` inside the same database
  transaction. It lets the payment endpoint lock a single row (`SELECT ... FOR UPDATE`) and check the
  balance without race conditions. The `payments` table remains the audit trail.

## Design notes

- Terms are stored as strings in the format `YYYY-FALL`, `YYYY-SPRING` or `YYYY-SUMMER`; no separate terms
  table is needed for this scope.
- `rate_limit_counters.student_no` is intentionally not a foreign key, so requests for unknown student
  numbers are also limited.
