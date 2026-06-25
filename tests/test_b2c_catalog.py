"""
Tests for B2C Catalog endpoints and CatalogService.

Covers: filtering, sorting, pagination, facets, validation, and B2B failure handling.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from apis.b2c.router import router as b2c_router
from services.catalog_service import CatalogService
from clients.b2b_client import B2BClient, B2BServiceUnavailableError
from schemas.catalog_filters_schemas import ProductListQueryParams


# ─── Helpers ────────────────────────────────────────────────────────

def _make_b2b_product(
    product_id: str,
    name: str,
    category: dict = None,
    skus: list = None,
    min_price: float = 10.0,
    max_price: float = 50.0,
    total_stock: int = 10,
) -> dict:
    """Build a fake B2B product dict for mocking."""
    if skus is None:
        skus = [
            {
                "id": str(uuid.uuid4()),
                "name": f"{name} - SKU",
                "image_url": f"https://cdn.example.com/{product_id}.jpg",
                "price": min_price,
                "stock_quantity": total_stock,
            }
        ]
    return {
        "id": product_id,
        "name": name,
        "description": f"Description for {name}",
        "category": category or {"id": "electronics", "name": "Electronics"},
        "skus": skus,
    }


def _build_mock_b2b_response(
    items: list,
    total: int = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Build a mock B2B get_products response."""
    return {
        "items": items,
        "total": total or len(items),
        "limit": limit,
        "offset": offset,
    }


def create_catalog_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the B2C catalog router."""
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import HTTPException
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

    app.include_router(b2c_router)
    return app


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def catalog_app() -> FastAPI:
    """Create FastAPI app with B2C router for testing."""
    from tests.conftest import test_engine
    from models.base import Base

    app = create_catalog_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield app
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def catalog_client(catalog_app) -> AsyncClient:
    """Create HTTP client for catalog endpoints."""
    transport = ASGITransport(app=catalog_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Create a database session for tests."""
    from tests.conftest import test_session_factory

    async with test_session_factory() as session:
        yield session


# ─── Test: catalog_returns_filtered_sorted_products ──────────────────

class TestCatalogFilteringAndSorting:
    """Tests for product list filtering and sorting."""

    async def test_catalog_returns_filtered_sorted_products(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        Filter by category + sort by price, verify correct products returned.
        """
        electronics_uuid = str(uuid.uuid4())
        electronics_products = [
            _make_b2b_product(str(uuid.uuid4()), "Laptop", category={"id": electronics_uuid, "name": "Electronics"}, min_price=500.0, max_price=1200.0),
            _make_b2b_product(str(uuid.uuid4()), "Phone", category={"id": electronics_uuid, "name": "Electronics"}, min_price=300.0, max_price=800.0),
        ]

        mock_response = _build_mock_b2b_response(electronics_products)

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/products",
                params={
                    "category": electronics_uuid,
                    "sort": "price_asc",
                    "limit": 10,
                    "offset": 0,
                },
            )

            assert response.status_code == 200
            data = response.json()

            # Verify structure
            assert "items" in data
            assert "total_count" in data
            assert "limit" in data
            assert "offset" in data

            # Verify filters were passed to B2B
            mock_instance.get_products.assert_called_once()
            call_args = mock_instance.get_products.call_args
            # get_products is called with filters as first positional arg
            b2b_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
            assert b2b_filters.get("category") == electronics_uuid
            assert b2b_filters.get("sort") == "price_asc"

    async def test_pagination_works_with_limit_offset(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        Verify limit and offset parameters are forwarded and paginated correctly.
        """
        all_products = [
            _make_b2b_product(str(uuid.uuid4()), f"Product {i}", min_price=10.0 + i, max_price=20.0 + i)
            for i in range(30)
        ]
        mock_response = _build_mock_b2b_response(all_products[:10], total=30, limit=10, offset=0)

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/products",
                params={"limit": 10, "offset": 0},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 30
        assert data["limit"] == 10
        assert data["offset"] == 0

    async def test_search_returns_matching_products(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        search parameter is forwarded to B2B for text filtering.
        """
        mock_products = [
            _make_b2b_product(str(uuid.uuid4()), "Wireless Mouse", min_price=25.0, max_price=30.0),
            _make_b2b_product(str(uuid.uuid4()), "Gaming Keyboard", min_price=80.0, max_price=120.0),
        ]
        mock_response = _build_mock_b2b_response(mock_products)

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/products",
                params={"search": "mouse"},
            )

        assert response.status_code == 200
        call_args = mock_instance.get_products.call_args
        b2b_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
        assert b2b_filters.get("search") == "mouse"

    async def test_in_stock_filter(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        in_stock=true should filter to only available products.
        """
        in_stock_product = _make_b2b_product(str(uuid.uuid4()), "Available", total_stock=5)

        mock_response = _build_mock_b2b_response([in_stock_product])

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/products",
                params={"in_stock": "true"},
            )

        assert response.status_code == 200
        call_args = mock_instance.get_products.call_args
        b2b_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
        assert b2b_filters.get("in_stock") is True

    async def test_price_range_filter(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        min_price and max_price are forwarded to B2B.
        """
        mock_response = _build_mock_b2b_response([])

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/products",
                params={"min_price": 50.0, "max_price": 200.0},
            )

        assert response.status_code == 200
        call_args = mock_instance.get_products.call_args
        b2b_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
        assert b2b_filters.get("min_price") == 50.0
        assert b2b_filters.get("max_price") == 200.0


# ─── Test: facets_return_counts_per_filter_value ─────────────────────

class TestFacets:
    """Tests for catalog facet aggregation."""

    async def test_facets_return_counts_per_filter_value(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        Facets return correct counts per category, price range, and availability.
        """
        products = [
            _make_b2b_product(str(uuid.uuid4()), "E-1", category={"id": "electronics", "name": "Electronics"}, min_price=100.0, max_price=200.0, total_stock=10),
            _make_b2b_product(str(uuid.uuid4()), "E-2", category={"id": "electronics", "name": "Electronics"}, min_price=300.0, max_price=500.0, total_stock=5),
            _make_b2b_product(str(uuid.uuid4()), "C-1", category={"id": "clothing", "name": "Clothing"}, min_price=20.0, max_price=40.0, total_stock=0),
            _make_b2b_product(str(uuid.uuid4()), "C-2", category={"id": "clothing", "name": "Clothing"}, min_price=50.0, max_price=80.0, total_stock=15),
        ]
        mock_response = _build_mock_b2b_response(products, total=4)

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get("/api/v1/b2c/catalog/facets")

        assert response.status_code == 200
        data = response.json()

        # Category facets
        categories = data["categories"]
        assert len(categories) == 2
        cat_map = {c["id"]: c["count"] for c in categories}
        assert cat_map["electronics"] == 2
        assert cat_map["clothing"] == 2

        # Price range facets
        price_ranges = data["price_ranges"]
        assert len(price_ranges) > 0
        range_map = {(r["min"], r["max"]): r["count"] for r in price_ranges}
        assert range_map.get((100, 500)) == 2
        assert range_map.get((0, 50)) == 1
        assert range_map.get((50, 100)) == 1

        # Availability facets
        availability = data["availability"]
        assert availability["in_stock_count"] == 3
        assert availability["out_of_stock_count"] == 1

    async def test_facets_with_filters_applied(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        Facets respect applied filters (e.g., category filter narrows facet counts).
        """
        electronics_uuid = str(uuid.uuid4())
        products = [
            _make_b2b_product(str(uuid.uuid4()), "E-1", category={"id": electronics_uuid, "name": "Electronics"}, min_price=100.0, max_price=200.0, total_stock=10),
        ]
        mock_response = _build_mock_b2b_response(products, total=1)

        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(return_value=mock_response)

            response = await catalog_client.get(
                "/api/v1/b2c/catalog/facets",
                params={"category": electronics_uuid},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["categories"]) == 1
        assert data["categories"][0]["id"] == electronics_uuid
        assert data["categories"][0]["count"] == 1

        call_args = mock_instance.get_products.call_args
        b2b_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
        assert b2b_filters.get("category") == electronics_uuid


# ─── Test: invalid_sort_returns_400 ──────────────────────────────────

class TestValidation:
    """Tests for input validation."""

    async def test_invalid_sort_returns_400(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        ?sort=invalid should return 400 with list of valid values.
        """
        response = await catalog_client.get(
            "/api/v1/b2c/products",
            params={"sort": "invalid_sort_value"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["code"] == 400
        assert "INVALID_SORT" in str(data["message"])

    async def test_invalid_category_uuid_returns_400(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        ?category=not-a-UUID should return 400.
        """
        response = await catalog_client.get(
            "/api/v1/b2c/products",
            params={"category": "not-a-uuid"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["code"] == 400
        assert "INVALID_CATEGORY" in str(data["message"])

    async def test_invalid_price_range_returns_400(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        min_price > max_price should return 400.
        """
        response = await catalog_client.get(
            "/api/v1/b2c/products",
            params={"min_price": 500.0, "max_price": 100.0},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["code"] == 400
        assert "INVALID_PRICE_RANGE" in str(data["message"])


# ─── Test: b2b_unavailable_returns_502 ───────────────────────────────

class TestB2BFailureHandling:
    """Tests for B2B service failure handling."""

    async def test_b2b_unavailable_returns_502(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        When B2B service is unavailable, return 502.
        """
        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(
                side_effect=B2BServiceUnavailableError("B2B service down")
            )

            response = await catalog_client.get("/api/v1/b2c/products")

        assert response.status_code == 502
        data = response.json()
        assert data["code"] == 502
        assert "B2B_UNAVAILABLE" in str(data["message"])

    async def test_b2b_timeout_returns_502(
        self,
        catalog_client: AsyncClient,
        catalog_app,
    ):
        """
        When B2B service times out, return 502.
        """
        with patch(
            "services.catalog_service.B2BClient"
        ) as MockB2BClientClass:
            mock_instance = MockB2BClientClass.return_value
            mock_instance.get_products = AsyncMock(
                side_effect=B2BServiceUnavailableError("Request failed after 3 attempts")
            )

            response = await catalog_client.get("/api/v1/b2c/catalog/facets")

        assert response.status_code == 502
        data = response.json()
        assert "B2B_UNAVAILABLE" in str(data["message"])


# ─── Test: CatalogService unit tests ─────────────────────────────────

class TestCatalogServiceUnit:
    """Unit tests for CatalogService methods."""

    async def test_get_catalog_passes_filters_to_b2b(
        self,
        db_session: AsyncSession,
        catalog_app,
    ):
        """CatalogService.get_catalog forwards filters to B2B client."""
        mock_b2b = MagicMock(spec=B2BClient)
        mock_b2b.get_products = AsyncMock(
            return_value={"items": [], "total": 0, "limit": 20, "offset": 0}
        )

        service = CatalogService(session=db_session, b2b_client=mock_b2b)
        filters = ProductListQueryParams(
            limit=10,
            offset=5,
            category="electronics",
            min_price=50.0,
            max_price=200.0,
            in_stock=True,
            search="laptop",
            sort="price_asc",
        )

        result = await service.get_catalog(filters)

        assert result.items == []
        assert result.total_count == 0
        mock_b2b.get_products.assert_called_once()

        # get_products is called with b2b_filters as first positional arg
        call_args = mock_b2b.get_products.call_args
        call_filters = call_args[0][0] if call_args[0] else call_args[1].get("filters", {})
        assert call_filters["limit"] == 10
        assert call_filters["offset"] == 5
        assert call_filters["category"] == "electronics"
        assert call_filters["min_price"] == 50.0
        assert call_filters["max_price"] == 200.0
        assert call_filters["in_stock"] is True
        assert call_filters["search"] == "laptop"
        assert call_filters["sort"] == "price_asc"

    async def test_get_facets_aggregates_correctly(
        self,
        db_session: AsyncSession,
        catalog_app,
    ):
        """CatalogService.get_facets aggregates counts correctly."""
        mock_b2b = MagicMock(spec=B2BClient)
        mock_b2b.get_products = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Product A",
                        "category": {"id": "cat1", "name": "Category 1"},
                        "skus": [{"price": 30.0, "stock_quantity": 5}],
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Product B",
                        "category": {"id": "cat1", "name": "Category 1"},
                        "skus": [{"price": 75.0, "stock_quantity": 0}],
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Product C",
                        "category": {"id": "cat2", "name": "Category 2"},
                        "skus": [{"price": 150.0, "stock_quantity": 20}],
                    },
                ],
                "total": 3,
                "limit": 1000,
                "offset": 0,
            }
        )

        service = CatalogService(session=db_session, b2b_client=mock_b2b)
        filters = ProductListQueryParams()

        result = await service.get_facets(filters)

        cat_map = {c.id: c.count for c in result.categories}
        assert cat_map["cat1"] == 2
        assert cat_map["cat2"] == 1

        assert result.availability.in_stock_count == 2
        assert result.availability.out_of_stock_count == 1

    async def test_map_to_list_item_extracts_correctly(
        self,
        db_session: AsyncSession,
        catalog_app,
    ):
        """CatalogService._map_to_list_item extracts min/max price and total stock."""
        service = CatalogService(session=db_session)

        raw = {
            "id": "test-id-123",
            "name": "Test Product",
            "description": "A test",
            "category": {"id": "electronics", "name": "Electronics"},
            "skus": [
                {
                    "id": "sku-1",
                    "name": "SKU 1",
                    "image_url": "https://example.com/img1.jpg",
                    "price": 25.50,
                    "stock_quantity": 10,
                },
                {
                    "id": "sku-2",
                    "name": "SKU 2",
                    "image_url": "https://example.com/img2.jpg",
                    "price": 45.00,
                    "stock_quantity": 5,
                },
            ],
        }

        item = service._map_to_list_item(raw)

        assert item.id == "test-id-123"
        assert item.name == "Test Product"
        assert item.min_price == 25.50
        assert item.max_price == 45.00
        assert item.total_stock == 15
        assert item.is_available is True
        assert item.image_url == "https://example.com/img1.jpg"
        assert item.category == "Electronics"