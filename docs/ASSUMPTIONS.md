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
