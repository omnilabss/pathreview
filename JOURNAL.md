# Journal

## Week 7 — Issue selection

**Issue link:** https://github.com/ascherj/pathreview/issues/155

**Issue title:** Health check references `settings.redis_host`, which does not exist on Settings

**Tier:** [x] Tier 1  [ ] Tier 2  [ ] Tier 3

**Problem summary:**
The `/health` endpoint in `api/routes/health.py` is supposed to report whether Postgres, Redis, and the vector store are reachable, but the Redis check builds its client with `settings.redis_host` and `settings.redis_port`. The `Settings` class in `core/config.py` only defines a single `redis_url` field — there is no `redis_host` or `redis_port` attribute anywhere in the config — so that line raises an `AttributeError` on every request and the endpoint always reports Redis (and therefore the whole service) as unhealthy, regardless of whether Redis is actually up. A correct fix builds the Redis client from the existing `redis_url` setting instead (e.g. `redis.Redis.from_url(settings.redis_url)`), so the health check reflects Redis's real status. This affects the `api/` subsystem only and doesn't touch ingestion, RAG, or the frontend.

**Scope check ("Is this right for me?"):**
- Single file changed (`api/routes/health.py`), no cross-module ripple — the fix is a constructor call, not a design change.
- Root cause is fully understood and unambiguous: I confirmed directly in `core/config.py` that `redis_host`/`redis_port` don't exist, only `redis_url`.
- Small, testable in isolation (mock/patch `redis.Redis.from_url` in a unit test), no new dependencies.
- Labeled `good first issue` + `tier-1` on the tracker, consistent with a first Module 3 issue.

**Branch name:** fix/155-health-check-redis-host

**Setup confirmation:** [x] App runs locally at localhost:5173
*(Confirmed: `docker compose up -d`, `make setup`, and `make run` complete; frontend returns HTTP 200 at localhost:5173 and the API responds at localhost:8000. As a bonus, `curl localhost:8000/health` live-reproduces the exact bug in issue #155 — the server log shows `error="'Settings' object has no attribute 'redis_host'"` on every request.)*

**Cohort ledger:** [x] Issue added to cohort ledger
*(Done — row added to the cohort ledger, and issue #155 claimed via a comment on GitHub.)*

## Week 8 — Reproduction & solution planning

**Reproduction commit link:** https://github.com/omnilabss/pathreview/commit/c429467d0f7c37dd7616ff92ce3d548296a103b5

**Reproduction summary:**
I added a unit test (`tests/unit/test_health_check.py`) that calls the
`health_check()` endpoint directly with a mocked database and a mocked, fully
reachable Redis client. Even with Redis "up," the endpoint still marks Redis
`unhealthy` and raises `HTTPException(503)`, because `settings.redis_host` in
`api/routes/health.py` raises `AttributeError` (the `Settings` class only
defines `redis_url`). The captured log line is
`redis_health_check_failed error="'Settings' object has no attribute 'redis_host'"`,
and the endpoint returns `{'dependencies': {'postgres': 'healthy', 'redis':
'unhealthy', 'vector_db': 'healthy'}, ...}` — i.e. the broad `except Exception`
masks a config bug as a fake "Redis is down." (I first saw this live in Week 7
via `curl localhost:8000/health` while the app was running.)

**PLAN.md link:** https://github.com/omnilabss/pathreview/blob/fix/155-health-check-redis-host/PLAN.md

**Walkthrough video (recommended):** _Not recorded (optional / not graded)._

**Blockers or open questions:**
- No blockers on the fix itself — the change is a one-line switch to
  `redis.Redis.from_url(settings.redis_url, decode_responses=True)` in
  `api/routes/health.py`, and the reproduction test above will flip from
  failing to passing once that lands.
- One thing to decide in Week 9 (out of scope for #155, noted in PLAN.md):
  `redis.Redis(...).ping()` is a blocking call inside an `async def` endpoint.
  I plan to leave that as-is to keep the fix minimal, and only flag it as a
  possible follow-up rather than widen scope.
