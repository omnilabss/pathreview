# Solution plan

**Issue:** [#155 — Health check references `settings.redis_host`, which does not exist on `Settings`](https://github.com/ascherj/pathreview/issues/155)

### Understand

**Root cause.** The `/health` endpoint builds its Redis client with keyword
arguments read from the settings object:

```python
# api/routes/health.py
r = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=0,
    decode_responses=True,
)
```

But `core/config.py` `Settings` defines **only** a single Redis field —
`redis_url: str = "redis://localhost:6379/0"`. There is no `redis_host` or
`redis_port`. Evaluating `settings.redis_host` therefore raises
`AttributeError: 'Settings' object has no attribute 'redis_host'` *before* the
Redis client is even constructed.

**Expected vs. actual.**
- *Expected:* `/health` connects to Redis using the configured connection,
  runs `PING`, and reports `redis: "healthy"`; when Postgres, Redis, and the
  vector DB are all up, the endpoint returns HTTP 200.
- *Actual:* the `AttributeError` is swallowed by the endpoint's broad
  `except Exception`, so Redis is marked `"unhealthy"`, the overall status is
  forced to `"unhealthy"`, and the endpoint raises `HTTPException(503)` on
  **every** request — even when Redis is perfectly healthy. The bug is masked
  (a misleading "Redis is down" signal) rather than surfaced as a config error.

The rest of the codebase already treats `redis_url` as the single source of
truth (e.g. the app wiring and `safety/rate_limiter.py` operate on a Redis
client, not host/port), so the health check is the outlier.

### Map

Files involved:

- **`api/routes/health.py`** — the buggy Redis client construction
  (the Redis `try/except` block, ~lines 39–56). **This is the only production
  file that needs to change.**
- **`core/config.py`** — reference only; confirms `redis_url` is the field that
  exists and `redis_host`/`redis_port` do not. No change planned (see Risks for
  the rejected alternative).
- **`tests/unit/test_health_check.py`** — new test module (added in Week 8 as
  the reproduction) that will become the regression test for the fix.

### Plan

1. **Replace the client construction** in `api/routes/health.py` with a
   URL-based client: `redis.Redis.from_url(settings.redis_url, decode_responses=True)`.
   This matches the one Redis field that actually exists and mirrors how the
   rest of the app addresses Redis.
2. **Keep the health semantics intact** — still call `r.ping()`, still set
   `redis: "healthy"` on success and `"unhealthy"` on a genuine connection
   failure. The `try/except` stays; only the connection line changes.
3. **Confirm the reproduction test now passes** — the two tests in
   `tests/unit/test_health_check.py` should go from failing (503 /
   AttributeError) to passing (redis `"healthy"`, overall `"healthy"`).
4. **Add a failure-path test** — assert that when `r.ping()` raises
   (Redis genuinely down), the endpoint still reports `redis: "unhealthy"` and
   returns 503, so the fix doesn't paper over real outages.
5. **Run `make check` and `make test-unit`** to confirm lint/format/type checks
   and the full unit suite pass before opening the PR.

### Inputs & outputs

- **Input:** `settings.redis_url` (default `redis://localhost:6379/0`), read
  from environment / `.env` by `pydantic-settings`.
- **Output / change in behavior:** `GET /health` returns HTTP 200 with
  `dependencies.redis == "healthy"` when Redis is reachable, and continues to
  return HTTP 503 with `redis == "unhealthy"` only when Redis is genuinely
  unreachable. No change to the response schema, other dependencies, or any
  public API.

### Risks & unknowns

- **Rejected alternative — adding `redis_host`/`redis_port` to `Settings`.**
  This would also silence the `AttributeError`, but it splits Redis config
  across two representations (`redis_url` *and* host/port) that could drift out
  of sync, and it ignores the DB index encoded in the URL (`/0`). Fixing the
  call site to use `redis_url` is the smaller, more consistent change.
- **`decode_responses` behavior.** The original passed `decode_responses=True`;
  I must preserve it on `from_url` so any downstream expectations about
  str-vs-bytes replies are unchanged. (The health check only calls `ping()`, so
  low risk, but worth keeping identical.)
- **Synchronous client in an async endpoint.** `redis.Redis(...).ping()` is a
  blocking call inside an `async def`. This is pre-existing behavior and out of
  scope for #155; I will not switch to `redis.asyncio` here, to keep the fix
  minimal — but I'll note it as a possible follow-up.
- **Unknown:** whether any environment sets a non-default `redis_url` that the
  `from_url` parser handles differently (auth, TLS `rediss://`). `from_url`
  supports these, so this should be strictly more capable than the old
  host/port form, but I'll sanity-check against the `.env.example` value.

### Edge cases

- **Redis genuinely down / wrong URL:** `ping()` raises → caught → `redis:
  "unhealthy"`, overall `503`. (Covered by the planned failure-path test.)
- **`redis_url` with a non-zero DB index or credentials** (e.g.
  `redis://:pass@host:6379/2`, `rediss://…`): `from_url` must parse it without
  error.
- **Postgres or vector DB down but Redis up:** overall status still `503`, but
  `dependencies.redis` should now correctly read `"healthy"` — the fix must not
  regress the other independent checks.
- **All dependencies healthy:** endpoint returns 200 with every dependency
  `"healthy"` (the primary case that is broken today).
