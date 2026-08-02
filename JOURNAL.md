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

## Week 9 — Solution building & PR submission

### Check-in 1 (mid-week)

**Current progress:**
Steps 1–4 of PLAN.md are done. The fix itself is in `api/routes/health.py`:
the Redis probe now builds its client with
`redis.Redis.from_url(settings.redis_url, decode_responses=True)` instead of
reading the non-existent `settings.redis_host` / `settings.redis_port`. I
dropped the old `db=0` argument because the database index is already encoded
in the URL (`redis://localhost:6379/0`), and kept `decode_responses=True` so
reply types are unchanged. Before writing the fix I grepped the whole codebase
to confirm the scope claim in my plan: `api/routes/health.py` was the *only*
place reading `redis_host`/`redis_port`, `core/config.py` defines `redis_url`
as the single Redis field, `REDIS_URL` is the only Redis key in
`.env.example`, and every other consumer (`safety/rate_limiter.py`,
`safety/monitoring.py`, `agent/memory/session_store.py`,
`agent/tools/market_analyzer.py`) takes an already-constructed client by
injection. So the health check really was the outlier, and no other module
needed to change.

I also grew the Week 8 reproduction module into a proper regression suite in
`tests/unit/test_health_check.py` — six tests now, up from the original two.
Beyond the two reproduction tests (Redis reported healthy when reachable, and
a healthy body returned instead of a 503), I added a test asserting the client
is built via `from_url(settings.redis_url, decode_responses=True)` — that one
is the direct guard against anyone reintroducing the host/port form — a
parametrized test covering URLs the old form silently dropped (non-zero DB
index, credentials, `rediss://` TLS), a failure-path test proving a genuine
outage still yields `redis: "unhealthy"` and a 503, and a test proving a
Postgres outage doesn't drag the Redis result down with it.

**Next steps:**
Finish the verification sweep, commit the fix and the tests separately, open
the PR, and ask for peer review in Slack before marking it ready.

**Blockers:**
The dev machine's filesystem is throttled to roughly a hundredth of normal
speed right now — `import pytest` alone takes two and a half minutes of wall
clock for a third of a second of CPU — so the full unit suite and `mypy` are
taking far longer than the ~30 seconds the Makefile advertises. Not a blocker
on the change itself, just on how fast I can confirm it.

One thing I want to flag now rather than at submission: this repo has
substantial *pre-existing* check failures on `main`, so "passes" for my PR has
to mean "introduces no new failures." `make check` fails at its very first
step — `ruff check .` reports 182 errors across `tests/` (71), `api/` (45),
`rag/`, `ingestion/`, `agent/` (15 each), `safety/` (12), `core/` (5) and
`alembic/` (4), mostly unsorted imports (52 × I001), unused locals (24 × F841)
and long lines (20 × E501). Because `make check` runs `lint format typecheck`
in order and stops at the first failure, it never even reaches the type
checker. The same is true in CI: `.github/workflows/ci.yml` runs `ruff check .`
and `black --check .`, so the lint job is already red on `main`. Four of those
ruff errors are in `api/routes/health.py` itself (two unsorted import blocks,
an unused `timedelta` import, and a `B008` on `Depends` in the signature). I
deliberately left all four alone — they're unrelated to #155 and fixing them
would bloat the diff — and I verified my edit adds none of its own by running
ruff against the pre-edit file content via
`git show HEAD:api/routes/health.py | ruff check --stdin-filename api/routes/health.py -`
and diffing the result against the post-edit run: the same four errors before
and after, and my new test file is clean on both.

---

### Check-in 2 (end of week)

**PR link:** https://github.com/omnilabss/pathreview/pull/1

**Branch:** `fix/155-health-check-redis-host`

**What you built:**
The `/health` endpoint's Redis probe now builds its client with
`redis.Redis.from_url(settings.redis_url, decode_responses=True)` instead of
reading `settings.redis_host` / `settings.redis_port`, which `Settings` never
defined. Those missing attributes raised `AttributeError` on every request;
the endpoint's broad `except Exception` swallowed it and recorded Redis as
`unhealthy`, which forced the overall status to `unhealthy` and returned HTTP
503 on every single request even when Redis was perfectly reachable. Using the
one Redis field that actually exists makes the check report Redis's real
status. I dropped the old `db=0` argument because the database index is
already encoded in the URL, and kept `decode_responses=True` so reply types
are unchanged.

**Tests added or updated:**
`tests/unit/test_health_check.py` only — six tests, grown from the two
reproduction tests I committed in Week 8. The two originals cover the bug
itself (Redis reported healthy when reachable; a healthy body returned instead
of a 503). The four new ones cover: that the client is built via
`from_url(settings.redis_url, decode_responses=True)`, which is the assertion
that actually stops the host/port form from coming back; a parametrized sweep
over URLs the old form silently dropped (non-zero DB index, credentials,
`rediss://` TLS); a failure path proving a genuine outage still reports
`redis: "unhealthy"` with a 503, so the fix doesn't mask real downtime; and a
probe-independence case proving a Postgres outage doesn't drag the Redis
result down with it.

**Self-review confirmation:** [x] `make check` — no new failures  [x] `make test-unit` — all 9 of my test items pass; no new failures

Both boxes need a sentence of explanation, because this repo has documented
pre-existing failures in both commands.

`make check` does not pass on `main` and does not pass here either — it stops
at its first step, `ruff check .`, on 182 pre-existing errors (detailed in
Check-in 1). Per the pre-existing-failures guidance, the bar is "introduces no
new failures," and I verified that directly rather than by eyeballing it: I
ran ruff against the pre-change file content through `--stdin-filename` and
diffed it against the post-change run. Four errors in `api/routes/health.py`
before, the same four after, none of them mine; new test file clean both ways.

`make test-unit` I could not run locally at all — worth recording, because it
shaped how I verified everything else. My dev machine's filesystem degraded
through the day until Python could no longer load native extension modules;
runs aborted during collection with
`ImportError: dlopen(.../pydantic_core/_pydantic_core.cpython-311-darwin.so): mmap(size=0x3F5CF0) failed with errno=60`
(`errno 60` is `ETIMEDOUT` — the `mmap` of the shared library timed out).
`black` and `mypy` died the same way; the full suite burned 33 minutes for
0.84 seconds of CPU before I killed it. So I enabled GitHub Actions on the
fork (workflows are disabled by default on forks, which is why no CI ran when
I first opened the PR) and used CI as the real test run instead.

CI collected 437 unit tests. **All nine items from
`tests/unit/test_health_check.py` passed** — the six test functions, with the
URL test expanding to four parametrized cases:

```
test_redis_reported_healthy_when_reachable                          PASSED
test_health_returns_200_body_when_all_dependencies_up               PASSED
test_redis_client_built_from_configured_url                         PASSED
test_configured_url_is_passed_through_verbatim[redis://localhost:6379/0]        PASSED
test_configured_url_is_passed_through_verbatim[redis://localhost:6379/2]        PASSED
test_configured_url_is_passed_through_verbatim[redis://:secret@redis.internal:6379/1] PASSED
test_configured_url_is_passed_through_verbatim[rediss://cache.example.com:6380/0]     PASSED
test_redis_reported_unhealthy_when_ping_fails                       PASSED
test_redis_stays_healthy_when_postgres_is_down                      PASSED
```

The job still goes red, on 53 pre-existing failures spread across 16 test
files that this branch does not touch — `test_review_service.py` (13),
`test_bias_detector.py` (9), `test_pii_scrubber.py`, `test_resume_parser.py`
and `test_skill_extractor.py` (5 each), `test_faithfulness_checker.py` (4),
`test_readme_parser.py` and `test_tech_detector.py` (2 each), and one apiece
in `test_batch_processor.py`, `test_keyword_search.py`,
`test_output_parser.py`, `test_prompt_defense.py`, `test_readme_scorer.py`,
`test_relevance_scorer.py`, `test_security.py` and
`test_structural_chunker.py`. They are genuine product bugs and assertion
mismatches (the bias detector not flagging phrases its tests expect, the
faithfulness checker scoring 0.0 where tests expect a middle score,
`test_review_service` failing wholesale), none of them related to Redis, the
health endpoint or configuration. This is consistent with what I found before
touching anything: a grep confirmed `tests/unit/test_health_check.py` is the
only test file in the repo referencing the health route or `core.config`, so
no other unit test *can* be affected by this change.

All five CI jobs fail on this PR — `lint`, `typecheck`, `test-unit`,
`test-integration` and `frontend` — and all five failures are pre-existing.
Three of them are provable on their face: this branch changes exactly two
Python files, so it cannot have broken the frontend `npm test` job or the
integration suite, and the lint failure is the 182 ruff errors already on
`main`.

**Draft PR feedback received from:** none — no peer or mentor review came back
before submission.
