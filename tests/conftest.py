import os
from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENVIRONMENT", "test")

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
async def anonymous_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
async def client(anonymous_client: AsyncClient) -> AsyncClient:
    response = await anonymous_client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    assert response.status_code == 201
    return anonymous_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

