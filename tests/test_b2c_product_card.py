"""
Tests for B2C Product Card endpoint and ProductCardService.

Covers: full data retrieval, security (sensitive field exclusion),
visibility validation, stock status, and B2B failure handling.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException

from apis.b2c.product_card import router as product_card_router
from services.product_card_service import ProductCardService, ProductNotVisibleError
from clients.b2b_client import B2BClient, B2BServiceUnavailableError


# ─── Helpers ────────────────────────────────────────────────────────

def _make_b2b_product(
    product_id: str = None,
    status: str = "MODERATED",
    deleted: bool = False,
    is_hard_blocked: bool = False,
    title: str = "Test Product",
    skus: list = None,
    category: dict = None,
) -> dict:
    """Build a fake B2B product dict for mocking."""
    if product_id is None:
        product_id = str(uuid.uuid4())
    if skus is None:
        skus = [
            {
                "id": str(uuid.uuid4()),
                "name": "Test SKU - Black",
                "price": 9999,
                "discount": 500,
                "image": "https://cdn.example.com/sku.jpg",
                "active_quantity": 10,
                "cost_price": 5000,
                "reserved_quantity": 2,
                "characteristics": [
                    {"name": "Color", "value": "Black"},
                    {"name": "Size", "value": "M"},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Test SKU - White",
                "price": 8999,
                "discount": 0,
                "image": None,
                "active_quantity": 0,
                "cost_price": 4500,
                "reserved_quantity": 0,
                "characteristics": [
                    {"name": "Color", "value": "White"},
                ],
            },
        ]
    if category is None:
        category = {"id": str(uuid.uuid4()), "name": "Electronics"}

    return {
        "id": product_id,
        "slug": "test-product-slug",
        "title": title,
        "description": "A test product description",
        "status": status,
        "deleted": deleted,
        "is_hard_blocked": is_hard_blocked,
        "category": category,
        "images": [
            {"url": "https://cdn.example.com/img1.jpg", "ordering": 0},
            {"url": "https://cdn.example.com/img2.jpg", "ordering": 1},
        ],
        "characteristics": [
            {"name": "Brand", "value": "TestBrand"},
            {"name": "Origin", "value": "BR"},
        ],
        "skus": skus,
    }


def create_product_card_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the product card router."""
    from tests.conftest import override_get_async_session
    from models.database import get_async_session

    app = FastAPI()
    app.dependency_overrides[get_async_session] = override_get_async_session

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.detail},
        )

    app.include_router(product_card_router)
    return app


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mock_b2b_client_fixture():
    """Create a mock B2BClient instance."""
    mock = MagicMock(spec=B2BClient)
    mock.get_product_by_id = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def product_card_app(mock_b2b_client_fixture) -> FastAPI:
    """Create FastAPI app with product card router for testing with mocked B2BClient."""
    from tests.conftest import test_engine
    from models.base import Base

    app = create_product_card_test_app()
    
    # Patch B2BClient at the module level so ProductCardService uses our mock
    patcher = patch(
        "services.product_card_service.B2BClient",
        return_value=mock_b2b_client_fixture,
    )
    patcher.start()
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield app
    
    patcher.stop()
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def product_card_client(product_card_app) -> AsyncClient:
    """Create HTTP client for product card endpoint."""
    transport = ASGITransport(app=product_card_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ─── Test: product_card_returns_full_data_with_skus ─────────────────

class TestProductCardReturnsFullData:
    """Tests for successful product card retrieval."""

    async def test_product_card_returns_full_data_with_skus(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        Card returns all expected B2C fields including SKU list,
        images, characteristics, and category.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(product_id=product_id)
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 200
        data = response.json()

        # Product fields
        assert data["id"] == product_id
        assert data["slug"] == "test-product-slug"
        assert data["title"] == "Test Product"
        assert data["description"] == "A test product description"
        assert data["status"] == "MODERATED"

        # Category
        assert data["category"] is not None
        assert data["category"]["name"] == "Electronics"

        # Images
        assert len(data["images"]) == 2
        assert data["images"][0]["url"] == "https://cdn.example.com/img1.jpg"
        assert data["images"][0]["ordering"] == 0

        # Characteristics
        assert len(data["characteristics"]) == 2
        assert data["characteristics"][0]["name"] == "Brand"

        # SKUs
        assert len(data["skus"]) == 2
        assert data["skus"][0]["name"] == "Test SKU - Black"
        assert data["skus"][0]["price"] == 9999
        assert data["skus"][0]["discount"] == 500
        assert data["skus"][0]["in_stock"] is True
        assert data["skus"][0]["active_quantity"] == 10
        assert len(data["skus"][0]["characteristics"]) == 2


# ─── Test: cost_price_absent_in_response (CRITICAL SECURITY) ─────────

class TestSecuritySensitiveFields:
    """Tests to ensure sensitive fields are never exposed to B2C."""

    async def test_cost_price_absent_in_response(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        CRITICAL: cost_price must NEVER appear in B2C response.
        This is a seller-sensitive field that must be stripped.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(product_id=product_id)
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 200
        data = response.json()

        # SECURITY: cost_price must NOT be in any SKU
        for sku in data["skus"]:
            assert "cost_price" not in sku, (
                f"SECURITY VIOLATION: cost_price found in SKU response: {sku}"
            )

    async def test_reserved_quantity_absent_in_response(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        CRITICAL: reserved_quantity must NEVER appear in B2C response.
        This is internal stock data that must be stripped.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(product_id=product_id)
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 200
        data = response.json()

        # SECURITY: reserved_quantity must NOT be in any SKU
        for sku in data["skus"]:
            assert "reserved_quantity" not in sku, (
                f"SECURITY VIOLATION: reserved_quantity found in SKU response: {sku}"
            )


# ─── Test: blocked_product_returns_404 ────────────────────────────────

class TestVisibilityValidation:
    """Tests for product visibility validation."""

    async def test_blocked_product_returns_404(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        Product with is_hard_blocked=True must return 404.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(
            product_id=product_id,
            is_hard_blocked=True,
        )
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["code"] == 404
        assert "not found" in str(data["message"]).lower() or "not available" in str(data["message"]).lower()

    async def test_deleted_product_returns_404(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        Product with deleted=True must return 404.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(
            product_id=product_id,
            deleted=True,
        )
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 404

    async def test_non_moderated_product_returns_404(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        Product with status != MODERATED must return 404.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(
            product_id=product_id,
            status="DRAFT",
        )
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 404


# ─── Test: sku_without_stock_shown_as_unavailable ────────────────────

class TestStockStatus:
    """Tests for stock availability calculation."""

    async def test_sku_without_stock_shown_as_unavailable(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        SKU with active_quantity=0 must have in_stock=False.
        """
        product_id = str(uuid.uuid4())
        mock_product = _make_b2b_product(product_id=product_id)
        mock_b2b_client_fixture.get_product_by_id.return_value = mock_product

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 200
        data = response.json()

        # First SKU has active_quantity=10, should be in_stock=True
        black_sku = next(s for s in data["skus"] if s["name"] == "Test SKU - Black")
        assert black_sku["in_stock"] is True
        assert black_sku["active_quantity"] == 10

        # Second SKU has active_quantity=0, should be in_stock=False
        white_sku = next(s for s in data["skus"] if s["name"] == "Test SKU - White")
        assert white_sku["in_stock"] is False
        assert white_sku["active_quantity"] == 0


# ─── Test: b2b_unavailable_returns_502 ───────────────────────────────

class TestB2BFailureHandling:
    """Tests for B2B service failure handling."""

    async def test_b2b_service_unavailable_returns_502(
        self,
        product_card_client: AsyncClient,
        product_card_app,
        mock_b2b_client_fixture,
    ):
        """
        When B2B service is unavailable, return 502.
        """
        product_id = str(uuid.uuid4())
        mock_b2b_client_fixture.get_product_by_id.side_effect = B2BServiceUnavailableError(
            "B2B service down"
        )

        response = await product_card_client.get(f"/api/v1/products/{product_id}")

        assert response.status_code == 502
        data = response.json()
        assert data["code"] == 502


# ─── Test: ProductCardService unit tests ─────────────────────────────

class TestProductCardServiceUnit:
    """Unit tests for ProductCardService methods."""

    async def test_validate_visibility_rejects_non_moderated(self):
        """_validate_visibility raises for non-MODERATED status."""
        service = ProductCardService()
        raw = _make_b2b_product(status="DRAFT")

        with pytest.raises(ProductNotVisibleError):
            service._validate_visibility(raw)

    async def test_validate_visibility_rejects_deleted(self):
        """_validate_visibility raises for deleted products."""
        service = ProductCardService()
        raw = _make_b2b_product(deleted=True)

        with pytest.raises(ProductNotVisibleError):
            service._validate_visibility(raw)

    async def test_validate_visibility_rejects_blocked(self):
        """_validate_visibility raises for hard-blocked products."""
        service = ProductCardService()
        raw = _make_b2b_product(is_hard_blocked=True)

        with pytest.raises(ProductNotVisibleError):
            service._validate_visibility(raw)

    async def test_validate_visibility_accepts_valid(self):
        """_validate_visibility passes for valid MODERATED products."""
        service = ProductCardService()
        raw = _make_b2b_product(status="MODERATED", deleted=False, is_hard_blocked=False)

        # Should not raise
        service._validate_visibility(raw)

    async def test_build_sku_card_strips_sensitive_fields(self):
        """_build_sku_card explicitly excludes cost_price and reserved_quantity."""
        service = ProductCardService()
        raw_sku = {
            "id": str(uuid.uuid4()),
            "name": "Test SKU",
            "price": 9999,
            "discount": 500,
            "image": "https://example.com/img.jpg",
            "active_quantity": 5,
            "cost_price": 5000,
            "reserved_quantity": 1,
            "characteristics": [],
        }

        result = service._build_sku_card(raw_sku)

        assert result.price == 9999
        assert result.discount == 500
        assert result.in_stock is True
        assert result.active_quantity == 5
        # Verify sensitive fields are not in the result
        result_dict = result.model_dump()
        assert "cost_price" not in result_dict
        assert "reserved_quantity" not in result_dict

    async def test_build_sku_card_calculates_in_stock_false(self):
        """_build_sku_card sets in_stock=False when active_quantity=0."""
        service = ProductCardService()
        raw_sku = {
            "id": str(uuid.uuid4()),
            "name": "Empty SKU",
            "price": 5000,
            "discount": 0,
            "image": None,
            "active_quantity": 0,
            "cost_price": 2000,
            "reserved_quantity": 0,
            "characteristics": [],
        }

        result = service._build_sku_card(raw_sku)

        assert result.in_stock is False
        assert result.active_quantity == 0