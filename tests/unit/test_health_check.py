"""Reproduction and regression tests for issue #155.

Issue #155: The /health endpoint builds its Redis client from
``settings.redis_host`` and ``settings.redis_port`` (api/routes/health.py),
but ``core.config.Settings`` only defines ``redis_url``. Reading the missing
attributes raises ``AttributeError``, which the endpoint's broad
``except Exception`` swallows -- so Redis is *always* reported "unhealthy" and
``/health`` returns HTTP 503 even when Redis is actually reachable.

These tests exercise the endpoint with Postgres, Redis, and the vector DB all
mocked as reachable. They FAIL on the current code (reproducing the bug) and
should PASS once the Redis client is constructed from ``settings.redis_url``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestHealthCheckRedis:
    """Health-check behaviour around the Redis dependency (issue #155)."""

    @pytest.fixture
    def mock_db(self):
        """A DB session whose ``SELECT 1`` health probe succeeds."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=None)
        return db

    @pytest.mark.asyncio
    async def test_redis_reported_healthy_when_reachable(self, mock_db):
        """With a reachable Redis, /health must report redis as 'healthy'.

        Reproduces #155: today ``settings.redis_host`` raises AttributeError
        before the (mocked) Redis client is ever built, so the dependency is
        marked 'unhealthy' and this assertion fails.
        """
        from api.routes.health import health_check

        fake_client = MagicMock()
        fake_client.ping.return_value = True

        # Cover both the current constructor form (redis.Redis(host=..., port=...))
        # and the intended fixed form (redis.Redis.from_url(...)).
        with patch("redis.Redis") as redis_cls:
            redis_cls.return_value = fake_client
            redis_cls.from_url.return_value = fake_client
            result = await health_check(db=mock_db)

        assert result["dependencies"]["redis"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_returns_200_body_when_all_dependencies_up(self, mock_db):
        """When every dependency is reachable, /health returns a healthy body
        instead of raising HTTPException(503).

        Reproduces #155: today the swallowed AttributeError forces the overall
        status to 'unhealthy', so health_check raises HTTPException instead of
        returning.
        """
        from api.routes.health import health_check

        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with patch("redis.Redis") as redis_cls:
            redis_cls.return_value = fake_client
            redis_cls.from_url.return_value = fake_client
            result = await health_check(db=mock_db)

        assert result["status"] == "healthy"
