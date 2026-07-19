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

**Setup confirmation:** [ ] App runs locally at localhost:5173
*(Not yet confirmed — Docker is not installed on this machine, so `docker compose up` / `make setup` / `make run` haven't been run. Docker Desktop needs to be installed before this can be checked off.)*

**Cohort ledger:** [ ] Issue added to cohort ledger
*(Not yet done — the ledger is an external spreadsheet outside this repo; needs to be filled in manually.)*
