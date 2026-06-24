"""
Tests for B2B Products endpoint.

Tests the GET /api/v1/products/{product_id} endpoint for:
- MODERATED product returns full payload with blocking_reason=null, field_reports=[]
- BLOCKED product returns blocking_reason and field_reports
- Product from another seller returns 404
- Non-existent product returns 404
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product


class TestGetModeratedProduct:
    """Tests for MODERATED product retrieval."""

    @pytest.mark.asyncio
    async def test_get_moderated_product_returns_full_payload(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product_moderated: Product,
        test_seller_id: uuid.UUID,
    ):
        """
        Test that a MODERATED product returns full payload with
        blocking_reason=null and field_reports=[].
        """
        # Act
        response = await client.get(
            f"/api/v1/products/{test_product_moderated.id}",
            params={"seller_id": str(test_seller_id)},
        )

        # Assert
        assert response.status_code == 200
        
        result = response.json()
        assert result["id"] == str(test_product_moderated.id)
        assert result["name"] == "Moderated Product"
        assert result["status"] == "MODERATED"
        assert result["blocking_reason"] is None
        assert result["field_reports"] == []


class TestGetBlockedProduct:
    """Tests for BLOCKED product retrieval."""

    @pytest.mark.asyncio
    async def test_get_blocked_product_returns_blocking_reason_and_field_reports(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product_blocked: Product,
        test_seller_id: uuid.UUID,
    ):
        """
        Test that a BLOCKED product returns blocking_reason and field_reports.
        """
        # Act
        response = await client.get(
            f"/api/v1/products/{test_product_blocked.id}",
            params={"seller_id": str(test_seller_id)},
        )

        # Assert
        assert response.status_code == 200
        
        result = response.json()
        assert result["id"] == str(test_product_blocked.id)
        assert result["name"] == "Blocked Product"
        assert result["status"] == "BLOCKED"
        assert result["blocking_reason"] is not None
        assert result["blocking_reason"]["title"] == "Policy Violation"
        assert result["blocking_reason"]["description"] == "Product violates terms of service"
        assert result["field_reports"] is not None
        assert len(result["field_reports"]) == 1
        assert result["field_reports"][0]["field"] == "name"
        assert result["field_reports"][0]["issue"] == "Inappropriate content"


class TestGetOthersProduct:
    """Tests for product belonging to another seller."""

    @pytest.mark.asyncio
    async def test_get_others_product_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
    ):
        """
        Test that accessing a product belonging to another seller returns 404.
        
        When a seller tries to access a product that belongs to a different seller,
        the endpoint should return 404 Not Found.
        """
        # Arrange - Use a different seller_id that doesn't belong to the product
        other_seller_id = uuid.uuid4()

        # Act
        response = await client.get(
            f"/api/v1/products/{test_product.id}",
            params={"seller_id": str(other_seller_id)},
        )

        # Assert
        assert response.status_code == 404


class TestGetNonexistentProduct:
    """Tests for non-existent product retrieval."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(
        self,
        client: AsyncClient,
    ):
        """
        Test that accessing a non-existent product returns 404.
        
        When a product_id does not exist in the database,
        the endpoint should return 404 Not Found.
        """
        # Arrange - Use a random UUID that doesn't exist
        nonexistent_id = uuid.uuid4()

        # Act
        response = await client.get(f"/api/v1/products/{nonexistent_id}")

        # Assert
        assert response.status_code == 404