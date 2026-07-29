"""Regression tests for issue #155.

Issue #155: The /health endpoint built its Redis client from
``settings.redis_host`` and ``settings.redis_port`` (api/routes/health.py), but
``core.config.Settings`` only defines ``redis_url``. Reading the missing
attributes raised ``AttributeError``, which the endpoint's broad
``except Exception`` swallowed -- so Redis was *always* reported "unhealthy"
and ``/health`` returned HTTP 503 even when Redis was actually reachable.

The fix builds the client with ``redis.Redis.from_url(settings.redis_url, ...)``.
These tests pin that behaviour: Redis is reported healthy when it is reachable,
the client is built from the configured URL, and genuine outages are still
reported as unhealthy.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis
from fastapi import HTTPException

from core.config import settings


@pytest.mark.unit
class TestHealthCheckRedis:
    """Health-check behaviour around the Redis dependency (issue #155)."""

    @pytest.fixture
    def mock_db(self):
        """Return a DB session whose ``SELECT 1`` health probe succeeds."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=None)
        return db

    @pytest.fixture
    def reachable_redis(self):
        """Patch ``redis.Redis`` so ``from_url`` yields a client that pings.

        Yields:
            The patched ``redis.Redis`` class mock. Its ``from_url`` return
            value is the fake client, so tests can assert on how the client
            was constructed.
        """
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with patch("redis.Redis") as redis_cls:
            redis_cls.from_url.return_value = fake_client
            yield redis_cls

    @pytest.mark.asyncio
    async def test_redis_reported_healthy_when_reachable(self, mock_db, reachable_redis):
        """With a reachable Redis, /health reports the dependency as healthy."""
        from api.routes.health import health_check

        result = await health_check(db=mock_db)

        assert result["dependencies"]["redis"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_returns_200_body_when_all_dependencies_up(
        self, mock_db, reachable_redis
    ):
        """When every dependency is reachable, /health returns a healthy body.

        Before the fix the swallowed ``AttributeError`` forced the overall
        status to "unhealthy", so the endpoint raised ``HTTPException(503)``
        instead of returning.
        """
        from api.routes.health import health_check

        result = await health_check(db=mock_db)

        assert result["status"] == "healthy"
        assert result["dependencies"] == {
            "postgres": "healthy",
            "redis": "healthy",
            "vector_db": "healthy",
        }

    @pytest.mark.asyncio
    async def test_redis_client_built_from_configured_url(self, mock_db, reachable_redis):
        """The client is built from ``settings.redis_url``, not host/port.

        This is the direct guard against reintroducing #155: ``Settings`` has
        no ``redis_host``/``redis_port``, so any keyword-argument form would
        raise ``AttributeError`` again.
        """
        from api.routes.health import health_check

        await health_check(db=mock_db)

        reachable_redis.from_url.assert_called_once_with(
            settings.redis_url, decode_responses=True
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "redis_url",
        [
            "redis://localhost:6379/0",
            "redis://localhost:6379/2",
            "redis://:secret@redis.internal:6379/1",
            "rediss://cache.example.com:6380/0",
        ],
    )
    async def test_configured_url_is_passed_through_verbatim(
        self, mock_db, reachable_redis, redis_url
    ):
        """Non-default URLs (DB index, credentials, TLS) reach the client as-is.

        The old host/port form silently dropped everything the URL encoded
        beyond the host and port.
        """
        from api.routes.health import health_check

        with patch.object(settings, "redis_url", redis_url):
            result = await health_check(db=mock_db)

        reachable_redis.from_url.assert_called_once_with(redis_url, decode_responses=True)
        assert result["dependencies"]["redis"] == "healthy"

    @pytest.mark.asyncio
    async def test_redis_reported_unhealthy_when_ping_fails(self, mock_db):
        """A genuine Redis outage is still reported as unhealthy with a 503.

        The fix must not paper over real outages -- only the fake ones caused
        by the missing settings attribute.
        """
        from api.routes.health import health_check

        fake_client = MagicMock()
        fake_client.ping.side_effect = redis.exceptions.ConnectionError("connection refused")

        with patch("redis.Redis") as redis_cls:
            redis_cls.from_url.return_value = fake_client
            with pytest.raises(HTTPException) as exc_info:
                await health_check(db=mock_db)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["dependencies"]["redis"] == "unhealthy"
        assert exc_info.value.detail["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_redis_stays_healthy_when_postgres_is_down(self, reachable_redis):
        """Dependency checks stay independent: a Postgres outage is reported
        without dragging the Redis result down with it."""
        from api.routes.health import health_check

        failing_db = AsyncMock()
        failing_db.execute = AsyncMock(side_effect=Exception("connection refused"))

        with pytest.raises(HTTPException) as exc_info:
            await health_check(db=failing_db)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["dependencies"]["postgres"] == "unhealthy"
        assert exc_info.value.detail["dependencies"]["redis"] == "healthy"
