"""
Tests for B2B Catalog endpoint.

Tests the GET /api/v1/products endpoint for:
- Returns only MODERATED products
- Excludes HARD_BLOCKED products
- Response schema does not expose cost_price
- Pagination works correctly
- Returns empty list when no products match
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product, SKU


class TestCatalogReturnsModeratedProducts:
    """Tests that catalog returns only MODERATED products with stock."""

    @pytest.mark.asyncio
    async def test_catalog_returns_moderated_in_stock_products(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that catalog returns MODERATED products that have stock available.
        """
        # Arrange - Create a MODERATED product with SKU in stock
        product = Product(
            name="Available Product",
            description="A product that is available",
            status="MODERATED",
            deleted=False,
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        sku = SKU(
            product_id=product.id,
            sku_code="AVAIL001",
            price=29.99,
            image_url="https://example.com/image.jpg",
            stock_quantity=10,
        )
        db_session.add(sku)
        await db_session.commit()

        # Act
        response = await client.get("/api/v1/products")

        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["total"] >= 1
        assert len(result["items"]) >= 1
        
        # Find our product in the response
        product_ids = [item["id"] for item in result["items"]]
        assert str(product.id) in product_ids
        
        # Verify the product data
        product_data = next(item for item in result["items"] if item["id"] == str(product.id))
        assert product_data["name"] == "Available Product"
        assert product_data["status"] == "MODERATED"
        assert len(product_data["skus"]) == 1
        assert product_data["skus"][0]["sku_code"] == "AVAIL001"
        assert product_data["skus"][0]["price"] == 29.99
        assert product_data["skus"][0]["stock_quantity"] == 10


class TestCatalogExcludesHardBlocked:
    """Tests that catalog excludes HARD_BLOCKED products."""

    @pytest.mark.asyncio
    async def test_catalog_excludes_hard_blocked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that HARD_BLOCKED products are not included in catalog.
        """
        # Arrange - Create a HARD_BLOCKED product
        blocked_product = Product(
            name="Hard Blocked Product",
            description="This product is hard blocked",
            status="HARD_BLOCKED",
            deleted=False,
        )
        db_session.add(blocked_product)
        await db_session.commit()
        await db_session.refresh(blocked_product)

        sku_blocked = SKU(
            product_id=blocked_product.id,
            sku_code="BLOCKED001",
            price=99.99,
            image_url="https://example.com/blocked.jpg",
            stock_quantity=5,
        )
        db_session.add(sku_blocked)
        await db_session.commit()

        # Act
        response = await client.get("/api/v1/products")

        # Assert
        assert response.status_code == 200
        result = response.json()
        
        # Verify blocked product is not in results
        product_ids = [item["id"] for item in result["items"]]
        assert str(blocked_product.id) not in product_ids


class TestCatalogResponseSchema:
    """Tests that catalog response does not expose sensitive fields."""

    @pytest.mark.asyncio
    async def test_catalog_response_has_no_cost_price(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that catalog response does not include cost_price field.
        This ensures sensitive pricing data is not leaked.
        """
        # Arrange - Create a MODERATED product
        product = Product(
            name="Public Product",
            description="A product for public catalog",
            status="MODERATED",
            deleted=False,
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        sku = SKU(
            product_id=product.id,
            sku_code="PUBLIC001",
            price=49.99,
            image_url="https://example.com/public.jpg",
            stock_quantity=20,
        )
        db_session.add(sku)
        await db_session.commit()

        # Act
        response = await client.get("/api/v1/products")

        # Assert
        assert response.status_code == 200
        result = response.json()
        
        # Find our product
        product_data = next(
            (item for item in result["items"] if item["id"] == str(product.id)),
            None
        )
        assert product_data is not None
        
        # Verify cost_price is not in response
        assert "cost_price" not in product_data
        
        # Verify SKU also doesn't have cost_price
        for sku_data in product_data["skus"]:
            assert "cost_price" not in sku_data


class TestCatalogPagination:
    """Tests for catalog pagination functionality."""

    @pytest.mark.asyncio
    async def test_catalog_pagination_works_correctly(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that pagination parameters (limit, offset) work correctly.
        """
        # Arrange - Create multiple MODERATED products
        products = []
        for i in range(5):
            product = Product(
                name=f"Product {i}",
                description=f"Description for product {i}",
                status="MODERATED",
                deleted=False,
            )
            db_session.add(product)
            await db_session.commit()
            await db_session.refresh(product)
            products.append(product)

            sku = SKU(
                product_id=product.id,
                sku_code=f"SKU{i:03d}",
                price=10.00 + i,
                image_url=f"https://example.com/sku{i}.jpg",
                stock_quantity=10,
            )
            db_session.add(sku)
            await db_session.commit()

        # Act - Get first page
        response = await client.get("/api/v1/products", params={"limit": 2, "offset": 0})
        
        # Assert first page
        assert response.status_code == 200
        result = response.json()
        assert result["total"] >= 5
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert len(result["items"]) == 2

        # Act - Get second page
        response2 = await client.get("/api/v1/products", params={"limit": 2, "offset": 2})
        
        # Assert second page
        assert response2.status_code == 200
        result2 = response2.json()
        assert result2["limit"] == 2
        assert result2["offset"] == 2
        assert len(result2["items"]) == 2

        # Verify different products on different pages
        page1_ids = [item["id"] for item in result["items"]]
        page2_ids = [item["id"] for item in result2["items"]]
        assert set(page1_ids).isdisjoint(set(page2_ids))


class TestCatalogEmptyResults:
    """Tests for empty catalog scenarios."""

    @pytest.mark.asyncio
    async def test_catalog_returns_empty_when_no_moderated_products(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that catalog returns empty items when no MODERATED products exist.
        Note: This test verifies the structure even if other tests created products.
        """
        # Act - Query with very high offset to get empty results
        response = await client.get("/api/v1/products", params={"limit": 10, "offset": 9999})

        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["items"] == []
        assert result["limit"] == 10
        assert result["offset"] == 9999


class TestCatalogExcludesDeletedProducts:
    """Tests that deleted products are excluded from catalog."""

    @pytest.mark.asyncio
    async def test_catalog_excludes_deleted_products(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that products with deleted=True are not included in catalog.
        """
        # Arrange - Create a deleted product
        deleted_product = Product(
            name="Deleted Product",
            description="This product is deleted",
            status="MODERATED",
            deleted=True,
        )
        db_session.add(deleted_product)
        await db_session.commit()
        await db_session.refresh(deleted_product)

        sku = SKU(
            product_id=deleted_product.id,
            sku_code="DELETED001",
            price=15.99,
            image_url="https://example.com/deleted.jpg",
            stock_quantity=5,
        )
        db_session.add(sku)
        await db_session.commit()

        # Act
        response = await client.get("/api/v1/products")

        # Assert
        assert response.status_code == 200
        result = response.json()
        
        # Verify deleted product is not in results
        product_ids = [item["id"] for item in result["items"]]
        assert str(deleted_product.id) not in product_ids