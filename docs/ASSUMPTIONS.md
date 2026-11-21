# Assumptions and Design Decisions

This file records interpretations of the assignment and the policy document. It is updated as the
project progresses and summarized in the README.

## Money and rounding

- All amounts are stored as `NUMERIC(12,2)` and handled as `Decimal`; floating point is never used.
- Amounts are rounded to 2 decimal places using half-up rounding. Inputs with more than 2 decimals are rejected.
- A single currency per tuition record is stored (default `USD`, matching the policy document).

## Balance scope (term vs overall)

- Query Tuition returns the overall tuition total and balance for the student, plus a per-term breakdown.
- Pay Tuition is term-specific: `amount` must be positive and must not exceed that term's outstanding balance.
  Overpayments are not supported.

## Data model

- Terms are free-form strings validated against `YYYY-FALL`, `YYYY-SPRING` or `YYYY-SUMMER`.
- Each student has at most one tuition record per term (`UNIQUE (student_id, term)`).
- `tuitions.paid_amount` is a running total updated in the same transaction as each payment insert;
  `payments` is the immutable audit trail. See [er-diagram.md](er-diagram.md).

## Add Tuition duplicate handling

- Add Tuition is create-or-update keyed by `(studentNo, term)`: an existing record's amount and currency
  are replaced; otherwise a new record is created.
- If the student number does not exist yet, the student record is created automatically (admin is the
  system of record for tuition assessment).
- An update that would set `amount` below the already paid amount is rejected (`409 Conflict`).
- Changing the currency of a record that already has payments is rejected (`409 Conflict`).
- In a batch CSV, each row is processed independently; duplicate `(studentNo, term)` rows in the same
  file are applied in order (last one wins) and each is reported.

## Identity and authorization

- Authentication uses JWT bearer tokens issued by `POST /api/v1/auth/login` for seeded demo users.
- Roles: `student`, `bank`, `admin`.
- Banking endpoints accept the `bank` role (any student) and the `student` role (own student number only).
  The student number is taken from the token subject; a mismatching path/body value returns `403`.

## Mobile query rate limit

- Limited to 3 calls per student number per calendar day, keyed by student number, not client IP.
- The day boundary is computed in the `Europe/Istanbul` time zone.
- Calls for unknown student numbers also count toward the limit (reduces enumeration).
- The limit is enforced both at the gateway and inside the API (database counter, for testability).

## API Gateway

- Kong (DB-less, declarative config) is used as the gateway, locally and in the cloud, so the same
  configuration is used everywhere. Azure API Management Consumption tier was not chosen because it does
  not support `rate-limit-by-key`, which is needed for the per-student limit.
