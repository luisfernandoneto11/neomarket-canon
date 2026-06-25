"""
Tests for B2C Cart endpoints and CartService.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product, SKU
from models.database import get_async_session as original_get_async_session
from apis.b2c.router import router as b2c_cart_router
from services.cart_service import CartService


def create_cart_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the B2C cart router."""
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import HTTPException

    app = FastAPI()

    from tests.conftest import override_get_async_session
    app.dependency_overrides[original_get_async_session] = override_get_async_session

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.detail},
        )

    app.include_router(b2c_cart_router)
    return app


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def cart_app() -> FastAPI:
    """Create FastAPI app with cart router for testing."""
    app = create_cart_test_app()
    from tests.conftest import test_engine
    from models.base import Base
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield app
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def cart_client(cart_app) -> AsyncClient:
    """Create HTTP client for cart endpoints."""
    transport = ASGITransport(app=cart_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Create a database session for tests."""
    from tests.conftest import test_session_factory
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_product_moderated(db_session: AsyncSession) -> Product:
    """Create a MODERATED product with an available SKU."""
    product = Product(
        name="Cart Test Product",
        description="A product for cart tests",
        status="MODERATED",
        blocking_reason=None,
        field_reports=[],
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)

    sku = SKU(
        product_id=product.id,
        sku_code="CART-SKU-001",
        price=29.99,
        image_url="https://example.com/cart-product.jpg",
        on_hand=100,
        active_quantity=100,
        reserved_quantity=0,
    )
    db_session.add(sku)
    await db_session.commit()
    await db_session.refresh(sku)

    return product


@pytest_asyncio.fixture
async def test_sku(test_product_moderated: Product, db_session: AsyncSession) -> SKU:
    """Get the SKU created for cart testing."""
    from sqlalchemy import select as sql_select
    query = sql_select(SKU).where(
        SKU.product_id == test_product_moderated.id
    )
    result = await db_session.execute(query)
    return result.scalars().first()


class TestAddItemIncrementsQuantity:
    """Tests for adding items - increment vs duplicate behavior."""

    @pytest.mark.asyncio
    async def test_add_sku_increments_quantity_if_already_in_cart(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Adding the same SKU twice should increment quantity to 2 (not create duplicate).
        """
        session_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Add SKU first time
        response1 = await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 1},
            headers={"X-Session-Id": session_id},
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["total_items"] == 1

        # Add same SKU again
        response2 = await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 1},
            headers={"X-Session-Id": session_id},
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["total_items"] == 2

        # Verify only one item with quantity 2
        items = data2["items"]
        assert len(items) == 1
        assert items[0]["quantity"] == 2

    @pytest.mark.asyncio
    async def test_add_item_with_quantity_zero_via_update_removes(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Update an item to quantity=0 removes it from cart.
        """
        session_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Add item first
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 2},
            headers={"X-Session-Id": session_id},
        )

        # Update to 0 removes it
        response = await cart_client.put(
            f"/api/v1/b2c/cart/items/{sku_id}",
            json={"quantity": 0},
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 0
        assert len(data["items"]) == 0


class TestGetEnrichedCart:
    """Tests for cart enrichment with B2B data."""

    @pytest.mark.asyncio
    async def test_get_cart_enriched_with_b2b_data(
        self,
        cart_client: AsyncClient,
        db_session: AsyncSession,
        cart_app,
        test_product_moderated: Product,
        test_sku: SKU,
    ):
        """
        GET /cart should return items enriched with current SKU data (price, image, etc.).
        """
        session_id = str(uuid.uuid4())

        # Add item to cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": str(test_sku.id), "quantity": 3},
            headers={"X-Session-Id": session_id},
        )

        # Get cart
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        item = data["items"][0]

        # Verify enrichment
        assert item["sku_data"] is not None
        assert item["sku_data"]["price"] == 29.99
        assert item["sku_data"]["sku_code"] == "CART-SKU-001"
        assert item["sku_data"]["product_name"] == "Cart Test Product"
        assert item["sku_data"]["image_url"] == "https://example.com/cart-product.jpg"
        assert item["quantity"] == 3
        assert item["unavailable_reason"] is None

        # Verify total_amount = price * quantity in cents
        assert data["total_amount"] == int(29.99 * 100) * 3
        assert data["total_items"] == 3


class TestUnavailableReason:
    """Tests for unavailable item detection."""

    @pytest.mark.asyncio
    async def test_unavailable_sku_shown_with_reason(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Adding a non-existent SKU should show SKU_NOT_FOUND unavailable_reason.
        """
        session_id = str(uuid.uuid4())
        fake_sku_id = str(uuid.uuid4())

        # Add non-existent SKU to cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": fake_sku_id, "quantity": 1},
            headers={"X-Session-Id": session_id},
        )

        # Get cart
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["unavailable_reason"] == "SKU_NOT_FOUND"
        assert item["sku_data"] is None

        # Unavailable items still count in total_items, but not in total_amount
        assert data["total_amount"] == 0
        assert data["total_items"] == 1

    @pytest.mark.asyncio
    async def test_out_of_stock_sku_shown_with_reason(
        self,
        cart_client: AsyncClient,
        db_session: AsyncSession,
        cart_app,
    ):
        """
        Adding a SKU with 0 stock should show OUT_OF_STOCK unavailable_reason.
        """
        # Create a MODERATED product with out-of-stock SKU
        product = Product(
            name="Out of Stock Product",
            description="Test product",
            status="MODERATED",
            blocking_reason=None,
            field_reports=[],
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        sku = SKU(
            product_id=product.id,
            sku_code="OOS-SKU",
            price=10.00,
            image_url="https://example.com/oos.jpg",
            on_hand=0,
            active_quantity=0,
            reserved_quantity=0,
        )
        db_session.add(sku)
        await db_session.commit()
        await db_session.refresh(sku)

        session_id = str(uuid.uuid4())

        # Add to cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": str(sku.id), "quantity": 1},
            headers={"X-Session-Id": session_id},
        )

        # Get cart
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()

        item = data["items"][0]
        assert item["unavailable_reason"] == "OUT_OF_STOCK"
        assert item["sku_data"] is not None

    @pytest.mark.asyncio
    async def test_blocked_product_sku_shown_with_reason(
        self,
        cart_client: AsyncClient,
        db_session: AsyncSession,
        cart_app,
    ):
        """
        Adding a SKU from a BLOCKED product should show PRODUCT_BLOCKED.
        """
        product = Product(
            name="Blocked Product",
            description="Test product",
            status="BLOCKED",
            blocking_reason={"title": "Policy", "description": "Violation"},
            field_reports=[{"field": "name", "issue": "Bad"}],
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        sku = SKU(
            product_id=product.id,
            sku_code="BLOCKED-SKU",
            price=15.00,
            image_url="https://example.com/blocked.jpg",
            on_hand=10,
            active_quantity=10,
            reserved_quantity=0,
        )
        db_session.add(sku)
        await db_session.commit()
        await db_session.refresh(sku)

        session_id = str(uuid.uuid4())

        # Add to cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": str(sku.id), "quantity": 1},
            headers={"X-Session-Id": session_id},
        )

        # Get cart
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()

        item = data["items"][0]
        assert item["unavailable_reason"] == "PRODUCT_BLOCKED"


class TestMergeCart:
    """Tests for guest-to-user cart merge."""

    @pytest.mark.asyncio
    async def test_guest_cart_merged_on_login(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Guest adds items, logs in, merge with auth cart (MAX quantities).
        """
        guest_session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Guest adds item with quantity 2
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 2},
            headers={"X-Session-Id": guest_session_id},
        )

        # User adds same SKU with quantity 5 to auth cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 5},
            headers={"Authorization": f"Bearer {user_id}"},
        )

        # Merge guest into auth
        response = await cart_client.post(
            "/api/v1/b2c/cart/merge",
            headers={
                "Authorization": f"Bearer {user_id}",
                "X-Session-Id": guest_session_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Should have MAX(2, 5) = 5
        assert len(data["items"]) == 1
        assert data["items"][0]["quantity"] == 5

    @pytest.mark.asyncio
    async def test_merge_cart_guest_only_new_sku(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Merge when guest has a SKU not in auth cart - it should be added.
        """
        guest_session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Guest adds item
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 3},
            headers={"X-Session-Id": guest_session_id},
        )

        # Merge (auth cart is empty)
        response = await cart_client.post(
            "/api/v1/b2c/cart/merge",
            headers={
                "Authorization": f"Bearer {user_id}",
                "X-Session-Id": guest_session_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["quantity"] == 3

    @pytest.mark.asyncio
    async def test_merge_requires_bearer_token(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Merge without Bearer token should return 401.
        """
        response = await cart_client.post(
            "/api/v1/b2c/cart/merge",
            headers={"X-Session-Id": str(uuid.uuid4())},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_merge_requires_session_id(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Merge without X-Session-Id should return 400.
        """
        response = await cart_client.post(
            "/api/v1/b2c/cart/merge",
            headers={"Authorization": f"Bearer {uuid.uuid4()}"},
        )
        assert response.status_code == 400


class TestRemoveAndClear:
    """Tests for removing items and clearing cart."""

    @pytest.mark.asyncio
    async def test_remove_item(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        DELETE /cart/items/{sku_id} removes the item from cart.
        """
        session_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Add item
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 2},
            headers={"X-Session-Id": session_id},
        )

        # Remove item
        response = await cart_client.delete(
            f"/api/v1/b2c/cart/items/{sku_id}",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0
        assert data["total_items"] == 0

    @pytest.mark.asyncio
    async def test_clear_cart(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        DELETE /cart removes all items.
        """
        session_id = str(uuid.uuid4())

        # Add multiple items
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": str(uuid.uuid4()), "quantity": 1},
            headers={"X-Session-Id": session_id},
        )
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": str(uuid.uuid4()), "quantity": 2},
            headers={"X-Session-Id": session_id},
        )

        # Clear cart
        response = await cart_client.delete(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0
        assert data["total_items"] == 0
        assert data["total_amount"] == 0


class TestIDORProtection:
    """Tests for IDOR (Insecure Direct Object Reference) protection."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_user_cart(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        User A should not be able to access User B's cart.
        """
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # User B adds item to their cart
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 1},
            headers={"Authorization": f"Bearer {user_b_id}"},
        )

        # User A gets own cart (should be empty, not B's)
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"Authorization": f"Bearer {user_a_id}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0

    @pytest.mark.asyncio
    async def test_session_cart_not_accessible_by_other_session(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        One session should not access another session's cart.
        """
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())
        sku_id = str(uuid.uuid4())

        # Session A adds item
        await cart_client.post(
            "/api/v1/b2c/cart/items",
            json={"sku_id": sku_id, "quantity": 5},
            headers={"X-Session-Id": session_a},
        )

        # Session B gets own cart (should be empty)
        response = await cart_client.get(
            "/api/v1/b2c/cart",
            headers={"X-Session-Id": session_b},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0

    @pytest.mark.asyncio
    async def test_authentication_required(
        self,
        cart_client: AsyncClient,
        cart_app,
    ):
        """
        Requests without Bearer token or X-Session-Id should return 401.
        """
        response = await cart_client.get("/api/v1/b2c/cart")
        assert response.status_code == 401


class TestCartServiceUnit:
    """Unit tests for CartService methods."""

    @pytest.mark.asyncio
    async def test_get_or_create_cart_by_session(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService creates cart by session_id when no user_id."""
        service = CartService(db_session)
        session_id = "test-session-123"

        cart = await service.get_or_create_cart(session_id=session_id)
        assert cart.id is not None
        assert cart.session_id == session_id
        assert cart.user_id is None

    @pytest.mark.asyncio
    async def test_get_or_create_cart_by_user(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService creates cart by user_id when provided."""
        service = CartService(db_session)
        user_id = str(uuid.uuid4())

        cart = await service.get_or_create_cart(user_id=user_id)
        assert cart.id is not None
        assert str(cart.user_id) == user_id
        assert cart.session_id is None

    @pytest.mark.asyncio
    async def test_get_existing_cart(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService returns existing cart on second call."""
        service = CartService(db_session)
        user_id = str(uuid.uuid4())

        cart1 = await service.get_or_create_cart(user_id=user_id)
        cart2 = await service.get_or_create_cart(user_id=user_id)
        assert cart1.id == cart2.id

    @pytest.mark.asyncio
    async def test_add_new_item(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService.add_item creates new item."""
        service = CartService(db_session)
        cart = await service.get_or_create_cart(session_id="test-session")

        item = await service.add_item(cart=cart, sku_id=str(uuid.uuid4()), quantity=2)
        assert item is not None
        assert item.quantity == 2

    @pytest.mark.asyncio
    async def test_add_existing_item_increments(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService.add_item increments quantity for existing SKU."""
        service = CartService(db_session)
        cart = await service.get_or_create_cart(session_id="test-session")
        sku_id = str(uuid.uuid4())

        await service.add_item(cart=cart, sku_id=sku_id, quantity=1)
        item = await service.add_item(cart=cart, sku_id=sku_id, quantity=2)
        assert item.quantity == 3

    @pytest.mark.asyncio
    async def test_update_item(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService.update_item changes quantity."""
        service = CartService(db_session)
        cart = await service.get_or_create_cart(session_id="test-session")
        sku_id = str(uuid.uuid4())

        await service.add_item(cart=cart, sku_id=sku_id, quantity=1)
        item = await service.update_item(cart=cart, sku_id=sku_id, quantity=5)
        assert item.quantity == 5

    @pytest.mark.asyncio
    async def test_update_item_zero_removes(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService.update_item with quantity=0 removes the item."""
        service = CartService(db_session)
        cart = await service.get_or_create_cart(session_id="test-session")
        sku_id = str(uuid.uuid4())

        await service.add_item(cart=cart, sku_id=sku_id, quantity=3)
        item = await service.update_item(cart=cart, sku_id=sku_id, quantity=0)
        assert item is None

    @pytest.mark.asyncio
    async def test_remove_item(
        self,
        db_session: AsyncSession,
        cart_app,
    ):
        """CartService.remove_item removes the item."""
        service = CartService(db_session)
        cart = await service.get_or_create_cart(session_id="test-session")
        sku_id = str(uuid.uuid4())

        await service.add_item(cart=cart, sku_id=sku_id, quantity=1)
        await service.remove_item(cart=cart, sku_id=sku_id)

        # Verify removed
        from sqlalchemy import select as sql_select
        from models.cart_models import CartItem
        query = sql_select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.sku_id == sku_id,
        )
        result = await db_session.execute(query)
        assert result.scalars().first() is None