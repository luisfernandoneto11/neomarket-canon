"""
Pytest configuration and fixtures for NeoMarket Moderation tests.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from models.base import Base
from models.product_moderation import ProductModeration
from models.product_blocking_reasons import ProductBlockingReason, get_seed_blocking_reasons
from apis.moderation.events import router

# Test database URL - using SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

# Create test session factory
test_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def setup_database():
    """Create all tables before tests and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed data for tests
    async with test_session_factory() as session:
        from models.database import seed_blocking_reasons
        await seed_blocking_reasons(session)
    
    yield
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_database) -> AsyncGenerator[AsyncSession, None]:
    """Create a new database session for each test."""
    async with test_session_factory() as session:
        yield session
        # Clean up after test
        await session.rollback()


@pytest_asyncio.fixture
async def blocking_reason(db_session: AsyncSession) -> ProductBlockingReason:
    """Create a blocking reason for tests."""
    from sqlalchemy import select
    seed_reasons = get_seed_blocking_reasons()
    first_reason_id = seed_reasons[0].id
    result = await db_session.execute(select(ProductBlockingReason).where(ProductBlockingReason.id == first_reason_id))
    reason = result.scalars().first()
    if reason is None:
        reason = seed_reasons[0]
        db_session.add(reason)
        await db_session.commit()
    return reason


@pytest_asyncio.fixture
async def sample_product_data() -> dict:
    """Sample product data for tests."""
    return {
        "title": "Test Product",
        "description": "A test product description",
        "category": "electronics",
        "product_images": ["image1.jpg", "image2.jpg"],
        "skus": [
            {
                "id": str(uuid.uuid4()),
                "name": "Test SKU",
                "image": "sku_image.jpg",
                "price": 99.99,
                "total_quantity": 100,
            }
        ],
    }


@pytest_asyncio.fixture
async def moderated_product(
    db_session: AsyncSession,
    blocking_reason: ProductBlockingReason,
) -> ProductModeration:
    """Create a product that has been previously moderated."""
    product = ProductModeration(
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        status="MODERATED",
        queue_priority=3,
        json_before=None,
        json_after={"title": "Original Title", "skus": []},
        blocking_reason_id=None,
        moderator_id=uuid.uuid4(),
        moderator_comment="Approved",
        date_moderation=datetime.utcnow(),
    )
    db_session.add(product)
    await db_session.commit()
    return product


@pytest_asyncio.fixture
async def blocked_product(
    db_session: AsyncSession,
    blocking_reason: ProductBlockingReason,
) -> ProductModeration:
    """Create a product that has been previously blocked."""
    product = ProductModeration(
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        status="BLOCKED",
        queue_priority=2,
        json_before=None,
        json_after={"title": "Blocked Product", "skus": []},
        blocking_reason_id=blocking_reason.id,
        moderator_id=uuid.uuid4(),
        moderator_comment="Blocked for policy violation",
        date_moderation=datetime.utcnow(),
    )
    db_session.add(product)
    await db_session.commit()
    return product


@pytest_asyncio.fixture
async def in_review_product(
    db_session: AsyncSession,
) -> ProductModeration:
    """Create a product currently in review."""
    product = ProductModeration(
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        status="IN_REVIEW",
        queue_priority=3,
        json_before={"title": "Old Title"},
        json_after={"title": "New Title"},
        moderator_id=uuid.uuid4(),
    )
    db_session.add(product)
    await db_session.commit()
    return product


@pytest.fixture
def mock_b2b_product():
    """Mock product data returned from B2B."""
    return {
        "title": "Updated Product Title",
        "description": "Updated description",
        "category": "electronics",
        "product_images": ["new_image1.jpg"],
        "skus": [
            {
                "id": str(uuid.uuid4()),
                "name": "Updated SKU",
                "image": "new_sku_image.jpg",
                "price": 149.99,
                "total_quantity": 50,
            }
        ],
    }


@pytest.fixture
def service_key():
    """Test service key."""
    return "test-service-key-123"


@pytest_asyncio.fixture
async def client(service_key: str, setup_database) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    from fastapi import FastAPI, Request, status
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import HTTPException
    
    app = FastAPI()
    
    # Add global exception handler for HTTP exceptions
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.detail}
        )
    
    app.include_router(router)
    
    # Override database session for testing
    from models.database import get_async_session
    
    async def override_get_async_session():
        async with test_session_factory() as session:
            yield session
        
    app.dependency_overrides[get_async_session] = override_get_async_session
    
    # Override the service key for testing
    import apis.moderation.events as events_module
    original_key = events_module.B2B_SERVICE_KEY
    events_module.B2B_SERVICE_KEY = service_key
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    # Restore original key and dependencies
    events_module.B2B_SERVICE_KEY = original_key
    app.dependency_overrides.clear()
