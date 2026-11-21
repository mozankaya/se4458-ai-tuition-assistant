"""Smoke test of the API Gateway routes, JWT protection and per-student rate limit.

Usage (gateway, API and database running; fresh seed and freshly started gateway):
    python gateway/smoke_test.py [--gateway http://localhost:8000]

The demo password is read from SEED_DEMO_PASSWORD (environment or .env). Results are printed and
saved to docs/traces/gateway_smoke_test.txt. The mobile check uses up the daily limit of one student;
to run it again: `docker compose restart gateway` and `python -m app.seed --reset` (in api/).
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "docs" / "traces" / "gateway_smoke_test.txt"


def demo_password() -> str:
    if os.environ.get("SEED_DEMO_PASSWORD"):
        return os.environ["SEED_DEMO_PASSWORD"]
    for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_DEMO_PASSWORD="):
            return line.split("=", 1)[1].strip()
    sys.exit("SEED_DEMO_PASSWORD is not set")


def main() -> None:
    parser = argparse.ArgumentParser(description="API Gateway smoke test")
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--student", default="20230003", help="student number used for the rate-limit check")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.gateway, timeout=15)
    lines: list[str] = [f"Gateway: {args.gateway}", ""]
    failures = 0

    def check(name: str, response: httpx.Response, expected: int, show_body: bool = True) -> httpx.Response:
        nonlocal failures
        ok = response.status_code == expected
        failures += not ok
        # "via: kong" means the API answered through the gateway; no via header means Kong answered itself.
        via = response.headers.get("via", "gateway itself")
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}: {response.request.method} {response.request.url.path} "
                     f"-> {response.status_code} (expected {expected}, answered by: {via})")
        lines.append(f"       body: {response.text[:200] if show_body else '(hidden: contains a token)'}")
        return response

    check("public route", client.get("/api/v1/health"), 200)
    check("protected route without token (gateway rejects)", client.get("/api/v1/banking/tuition/20230001"), 401)
    check("protected route with forged token (gateway rejects)",
          client.get("/api/v1/banking/tuition/20230001", headers={"Authorization": "Bearer abc.def.ghi"}), 401)

    login = check("login", client.post("/api/v1/auth/login",
                                       json={"username": "student1", "password": demo_password()}), 200,
                  show_body=False)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    check("protected route with valid token", client.get("/api/v1/banking/tuition/20230001", headers=headers), 200)
    check("other student's data with valid token (API rejects)",
          client.get("/api/v1/banking/tuition/20230002", headers=headers), 403)

    url = f"/api/v1/mobile/tuition/{args.student}"
    for i in range(1, 4):
        check(f"mobile query #{i}", client.get(url), 200)
    limited = check("mobile query #4 (rate limited, keyed by student number)",
                    client.get(url, headers={"X-Student-No": "spoofed-value"}), 429)
    lines.append(f"       rate-limit headers: limit={limited.headers.get('x-ratelimit-limit-day')} "
                 f"remaining={limited.headers.get('x-ratelimit-remaining-day')}")
    check("mobile query for a different student is not affected", client.get("/api/v1/mobile/tuition/20230004"), 200)

    check("unknown route", client.get("/api/v2/tuition/20230001"), 404)

    lines += ["", f"{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}"]
    report = "\n".join(lines)
    print(report)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(report + "\n", encoding="utf-8")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
