"""
Tests for B2C Order Cancellation endpoints.

Covers:
- Status validation (CREATED and PAID only)
- IDOR protection (404 for other user's order)
- Unreserve failure handling (CANCEL_PENDING status)
- ASSEMBLING or later status returns 409 CANCEL_NOT_ALLOWED
- user_id from JWT, not from body
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from models.base import Base
from models.database import get_async_session as original_get_async_session
from models.order_models import Order, OrderItem, OrderStatus
from apis.b2c.router import router as b2c_router
from clients.b2b_client import B2BClientError, B2BServiceUnavailableError


# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_cancel_order.db"

# Create test engine and session factory
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_async_session():
    """Override database dependency to use test database."""
    async with test_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


def create_cancel_test_app() -> FastAPI:
    """Create a minimal FastAPI app with B2C router."""
    app = FastAPI()
    app.dependency_overrides[original_get_async_session] = override_get_async_session

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.detail},
        )

    app.include_router(b2c_router)
    return app


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def setup_database():
    """Create all tables before tests and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def cancel_app(setup_database) -> FastAPI:
    """Create FastAPI app for cancel order tests."""
    return create_cancel_test_app()


@pytest_asyncio.fixture
async def cancel_client(cancel_app) -> AsyncClient:
    """Create HTTP client for cancel order endpoints."""
    transport = ASGITransport(app=cancel_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Create a database session for tests."""
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_user_id() -> uuid.UUID:
    """Create a test user ID."""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def other_user_id() -> uuid.UUID:
    """Create another test user ID for IDOR tests."""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def test_order_created(db_session: AsyncSession, test_user_id: uuid.UUID) -> Order:
    """Create a test order in CREATED status."""
    order = Order(
        id=uuid.uuid4(),
        user_id=test_user_id,
        status=OrderStatus.CREATED,
        total_amount=10000,
        idempotency_key=uuid.uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    
    # Add order items
    item = OrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        sku_id=uuid.uuid4(),
        product_title="Test Product",
        sku_name="Test SKU",
        unit_price=10000,
        quantity=1,
        total_price=10000,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest_asyncio.fixture
async def test_order_paid(db_session: AsyncSession, test_user_id: uuid.UUID) -> Order:
    """Create a test order in PAID status."""
    order = Order(
        id=uuid.uuid4(),
        user_id=test_user_id,
        status=OrderStatus.PAID,
        total_amount=20000,
        idempotency_key=uuid.uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    
    # Add order items
    item = OrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        sku_id=uuid.uuid4(),
        product_title="Paid Product",
        sku_name="Paid SKU",
        unit_price=20000,
        quantity=1,
        total_price=20000,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest_asyncio.fixture
async def test_order_assembling(db_session: AsyncSession, test_user_id: uuid.UUID) -> Order:
    """Create a test order in PROCESSING status (cannot cancel)."""
    order = Order(
        id=uuid.uuid4(),
        user_id=test_user_id,
        status=OrderStatus.PROCESSING,
        total_amount=15000,
        idempotency_key=uuid.uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest_asyncio.fixture
async def test_order_shipped(db_session: AsyncSession, test_user_id: uuid.UUID) -> Order:
    """Create a test order in SHIPPED status (cannot cancel)."""
    order = Order(
        id=uuid.uuid4(),
        user_id=test_user_id,
        status=OrderStatus.SHIPPED,
        total_amount=30000,
        idempotency_key=uuid.uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest_asyncio.fixture
async def test_order_other_user(db_session: AsyncSession, other_user_id: uuid.UUID) -> Order:
    """Create a test order belonging to another user (for IDOR tests)."""
    order = Order(
        id=uuid.uuid4(),
        user_id=other_user_id,
        status=OrderStatus.CREATED,
        total_amount=5000,
        idempotency_key=uuid.uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    
    item = OrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        sku_id=uuid.uuid4(),
        product_title="Other User Product",
        sku_name="Other SKU",
        unit_price=5000,
        quantity=1,
        total_price=5000,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(order)
    return order


class TestCancelOrderSuccess:
    """Tests for successful order cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_created_order_success(
        self,
        cancel_client: AsyncClient,
        test_order_created: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Cancel an order in CREATED status should succeed.
        B2B unreserve succeeds → CANCELLED
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(return_value={"ok": True})
            MockB2BClient.return_value = mock_client

            response = await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_created.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "CANCELLED"
        assert "cancelled successfully" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_cancel_paid_order_success(
        self,
        cancel_client: AsyncClient,
        test_order_paid: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Cancel an order in PAID status should succeed.
        B2B unreserve succeeds → CANCELLED
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(return_value={"ok": True})
            MockB2BClient.return_value = mock_client

            response = await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_paid.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "CANCELLED"


class TestCancelOrderIDOR:
    """Tests for IDOR (Insecure Direct Object Reference) protection."""

    @pytest.mark.asyncio
    async def test_cancel_other_user_order_returns_404(
        self,
        cancel_client: AsyncClient,
        test_order_other_user: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Attempting to cancel another user's order should return 404.
        IDOR: Never reveal existence of other user's resources.
        """
        response = await cancel_client.post(
            f"/api/v1/b2c/orders/{test_order_other_user.id}/cancel",
            headers={"Authorization": f"Bearer {test_user_id}"},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["message"] == "Order not found"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order_returns_404(
        self,
        cancel_client: AsyncClient,
        test_user_id: uuid.UUID,
    ):
        """
        Attempting to cancel a non-existent order should return 404.
        """
        fake_order_id = uuid.uuid4()
        response = await cancel_client.post(
            f"/api/v1/b2c/orders/{fake_order_id}/cancel",
            headers={"Authorization": f"Bearer {test_user_id}"},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["message"] == "Order not found"


class TestCancelOrderStatusValidation:
    """Tests for order status validation."""

    @pytest.mark.asyncio
    async def test_cancel_processing_order_returns_409(
        self,
        cancel_client: AsyncClient,
        test_order_assembling: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Attempting to cancel an order in PROCESSING status should return 409.
        Only CREATED and PAID can be cancelled.
        """
        response = await cancel_client.post(
            f"/api/v1/b2c/orders/{test_order_assembling.id}/cancel",
            headers={"Authorization": f"Bearer {test_user_id}"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["message"] == "CANCEL_NOT_ALLOWED"

    @pytest.mark.asyncio
    async def test_cancel_shipped_order_returns_409(
        self,
        cancel_client: AsyncClient,
        test_order_shipped: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Attempting to cancel an order in SHIPPED status should return 409.
        """
        response = await cancel_client.post(
            f"/api/v1/b2c/orders/{test_order_shipped.id}/cancel",
            headers={"Authorization": f"Bearer {test_user_id}"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["message"] == "CANCEL_NOT_ALLOWED"


class TestCancelOrderB2BFailure:
    """Tests for B2B unreserve failure handling."""

    @pytest.mark.asyncio
    async def test_cancel_b2b_service_unavailable_returns_cancel_pending(
        self,
        cancel_client: AsyncClient,
        test_order_created: Order,
        test_user_id: uuid.UUID,
    ):
        """
        When B2B service is unavailable, order should be marked as CANCEL_PENDING.
        This allows for async retry without blocking the user.
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(
                side_effect=B2BServiceUnavailableError("B2B service unavailable")
            )
            MockB2BClient.return_value = mock_client

            response = await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_created.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "CANCEL_PENDING"
        assert "retrying" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_cancel_b2b_client_error_returns_cancel_pending(
        self,
        cancel_client: AsyncClient,
        test_order_paid: Order,
        test_user_id: uuid.UUID,
    ):
        """
        When B2B returns a client error (4xx), order should be marked as CANCEL_PENDING.
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(
                side_effect=B2BClientError("B2B client error: 409 Conflict")
            )
            MockB2BClient.return_value = mock_client

            response = await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_paid.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "CANCEL_PENDING"


class TestCancelOrderDatabaseState:
    """Tests for database state after cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_order_updates_status_in_database(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
        test_order_created: Order,
        test_user_id: uuid.UUID,
    ):
        """
        Successful cancellation should update order status in database.
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(return_value={"ok": True})
            MockB2BClient.return_value = mock_client

            await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_created.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        # Verify database state
        query = select(Order).where(Order.id == test_order_created.id)
        result = await db_session.execute(query)
        updated_order = result.scalars().first()
        
        assert updated_order is not None
        assert updated_order.status == OrderStatus.CANCELLED
        assert updated_order.updated_at is not None

    @pytest.mark.asyncio
    async def test_cancel_pending_sets_timestamp(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
        test_order_created: Order,
        test_user_id: uuid.UUID,
    ):
        """
        CANCEL_PENDING status should set cancel_pending_since timestamp.
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(
                side_effect=B2BServiceUnavailableError("B2B service unavailable")
            )
            MockB2BClient.return_value = mock_client

            await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_created.id}/cancel",
                headers={"Authorization": f"Bearer {test_user_id}"},
            )

        # Verify database state
        query = select(Order).where(Order.id == test_order_created.id)
        result = await db_session.execute(query)
        updated_order = result.scalars().first()
        
        assert updated_order is not None
        assert updated_order.status == OrderStatus.CANCEL_PENDING
        assert updated_order.cancel_pending_since is not None


class TestCancelOrderJWTAuthentication:
    """Tests that user_id comes from JWT, not from body."""

    @pytest.mark.asyncio
    async def test_user_id_from_jwt_not_body(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
        test_order_created: Order,
        other_user_id: uuid.UUID,
    ):
        """
        user_id should be extracted from JWT (Authorization header), not from body.
        Even if body contains different user_id, JWT should be used.
        """
        with patch("apis.b2c.orders.B2BClient") as MockB2BClient:
            mock_client = MagicMock()
            mock_client.unreserve = AsyncMock(return_value={"ok": True})
            MockB2BClient.return_value = mock_client

            # Try to cancel with different user_id in body (should be ignored)
            response = await cancel_client.post(
                f"/api/v1/b2c/orders/{test_order_created.id}/cancel",
                headers={"Authorization": f"Bearer {other_user_id}"},
                json={"user_id": str(test_order_created.user_id)},  # Should be ignored
            )

        # Should return 404 because JWT user_id doesn't match order's user_id
        assert response.status_code == 404