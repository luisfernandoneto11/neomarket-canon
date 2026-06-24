"""
Tests for B2B SKU endpoint.

Tests the POST /api/v1/skus endpoint for:
- First SKU creation and moderation flow
- Second SKU creation (no status change)
- HARD_BLOCKED product rejection
- Validation errors
- Product not found
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product, SKU
from schemas.b2b_schemas import SKUCreateRequest


class TestFirstSKUCreation:
    """Tests for first SKU creation behavior."""

    @pytest.mark.asyncio
    async def test_first_sku_transitions_to_on_moderation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        mock_moderation_client,
    ):
        """
        Test that creating the first SKU for a product transitions
        the product status to ON_MODERATION.
        
        When the first SKU is created, the product should move from
        DRAFT to ON_MODERATION status.
        """
        # Arrange
        sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="FIRST-SKU-001",
            price=99.99,
            image_url="https://example.com/product.jpg",
            stock_quantity=10,
        )

        # Patch the moderation client in the service
        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            # Act
            response = await client.post(
                "/api/v1/skus",
                json=sku_data.model_dump(mode="json"),
            )

        # Assert
        assert response.status_code == 201
        
        # Verify SKU was created
        result = response.json()
        assert result["sku_code"] == "FIRST-SKU-001"
        assert result["price"] == 99.99
        assert result["stock_quantity"] == 10
        assert result["product_id"] == str(test_product.id)

        # Verify product status changed to ON_MODERATION
        await db_session.refresh(test_product)
        assert test_product.status == "ON_MODERATION"

    @pytest.mark.asyncio
    async def test_first_sku_sends_event_to_moderation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        mock_moderation_client,
    ):
        """
        Test that creating the first SKU sends an event to Moderation.
        
        When the first SKU is created, an event should be sent to
        the Moderation service to trigger the moderation workflow.
        """
        # Arrange
        sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="FIRST-SKU-002",
            price=149.99,
            image_url="https://example.com/product2.jpg",
            stock_quantity=5,
        )

        # Patch the moderation client in the service
        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            # Act
            response = await client.post(
                "/api/v1/skus",
                json=sku_data.model_dump(mode="json"),
            )

        # Assert
        assert response.status_code == 201
        
        # Verify send_event was called
        mock_moderation_client.send_event.assert_called_once()
        
        # Verify the event contains expected data
        call_args = mock_moderation_client.send_event.call_args
        event = call_args[0][0]  # First positional argument
        assert event.event_type == "FIRST_SKU_CREATED"
        assert event.payload.json_after["sku_code"] == "FIRST-SKU-002"
        assert event.payload.json_after["product_id"] == str(test_product.id)


class TestSecondSKUBehavior:
    """Tests for second and subsequent SKU creation behavior."""

    @pytest.mark.asyncio
    async def test_second_sku_does_not_change_status(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        mock_moderation_client,
    ):
        """
        Test that creating a second SKU does not change product status.
        
        After the first SKU has been created and the product is in
        ON_MODERATION status, subsequent SKUs should not change the status.
        """
        # Arrange - Create first SKU (transitions to ON_MODERATION)
        first_sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="FIRST-SKU-003",
            price=99.99,
            image_url="https://example.com/product.jpg",
            stock_quantity=10,
        )

        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            first_response = await client.post(
                "/api/v1/skus",
                json=first_sku_data.model_dump(mode="json"),
            )
            assert first_response.status_code == 201

        # Verify product is now ON_MODERATION
        await db_session.refresh(test_product)
        assert test_product.status == "ON_MODERATION"

        # Arrange - Create second SKU
        second_sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="SECOND-SKU-001",
            price=149.99,
            image_url="https://example.com/product2.jpg",
            stock_quantity=5,
        )

        # Act - Create second SKU
        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            second_response = await client.post(
                "/api/v1/skus",
                json=second_sku_data.model_dump(mode="json"),
            )

        # Assert
        assert second_response.status_code == 201
        
        # Verify product status remains ON_MODERATION (not changed)
        await db_session.refresh(test_product)
        assert test_product.status == "ON_MODERATION"

    @pytest.mark.asyncio
    async def test_second_sku_does_not_send_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        mock_moderation_client,
    ):
        """
        Test that creating a second SKU does not send event to Moderation.
        
        Only the first SKU should trigger an event to the Moderation service.
        Subsequent SKUs should not send any events.
        """
        # Arrange - Create first SKU (sends event)
        first_sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="FIRST-SKU-004",
            price=99.99,
            image_url="https://example.com/product.jpg",
            stock_quantity=10,
        )

        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            first_response = await client.post(
                "/api/v1/skus",
                json=first_sku_data.model_dump(mode="json"),
            )
            assert first_response.status_code == 201
            
            # Verify send_event was called for first SKU
            assert mock_moderation_client.send_event.call_count == 1

        # Reset mock to track new calls
        mock_moderation_client.send_event.reset_mock()

        # Arrange - Create second SKU
        second_sku_data = SKUCreateRequest(
            product_id=test_product.id,
            sku_code="SECOND-SKU-002",
            price=149.99,
            image_url="https://example.com/product2.jpg",
            stock_quantity=5,
        )

        # Act - Create second SKU
        with patch(
            "services.b2b_service.ModerationClient",
            return_value=mock_moderation_client,
        ):
            second_response = await client.post(
                "/api/v1/skus",
                json=second_sku_data.model_dump(mode="json"),
            )

        # Assert
        assert second_response.status_code == 201
        
        # Verify send_event was NOT called for second SKU
        mock_moderation_client.send_event.assert_not_called()


class TestHARDBlockedProduct:
    """Tests for HARD_BLOCKED product behavior."""

    @pytest.mark.asyncio
    async def test_hard_blocked_product_returns_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product_hard_blocked: Product,
    ):
        """
        Test that creating a SKU for a HARD_BLOCKED product returns 403.
        
        Products in HARD_BLOCKED status cannot be modified.
        The endpoint should return 403 Forbidden.
        """
        # Arrange
        sku_data = SKUCreateRequest(
            product_id=test_product_hard_blocked.id,
            sku_code="BLOCKED-SKU-001",
            price=99.99,
            image_url="https://example.com/product.jpg",
            stock_quantity=10,
        )

        # Act
        response = await client.post(
            "/api/v1/skus",
            json=sku_data.model_dump(mode="json"),
        )

        # Assert
        assert response.status_code == 403
        
        # Verify error message
        result = response.json()
        assert "HARD_BLOCKED" in result["message"]
        
        # Verify no SKU was created
        query = select(func.count(SKU.id)).where(
            SKU.product_id == test_product_hard_blocked.id
        )
        result = await db_session.execute(query)
        assert result.scalar() == 0


class TestValidationErrors:
    """Tests for validation error handling."""

    @pytest.mark.asyncio
    async def test_missing_image_url_returns_400(
        self,
        client: AsyncClient,
        test_product: Product,
    ):
        """
        Test that missing image_url returns 422 (validation error).
        
        The SKUCreateRequest schema requires image_url to be a valid URL.
        FastAPI/Pydantic returns 422 for schema validation failures.
        """
        # Arrange - SKU data without image_url
        sku_data = {
            "product_id": str(test_product.id),
            "sku_code": "NO-IMAGE-SKU",
            "price": 99.99,
            "stock_quantity": 10,
        }

        # Act
        response = await client.post(
            "/api/v1/skus",
            json=sku_data,
        )

        # Assert
        assert response.status_code == 422
        
        # Verify error details
        result = response.json()
        # FastAPI returns validation error format
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_invalid_price_returns_400(
        self,
        client: AsyncClient,
        test_product: Product,
    ):
        """
        Test that invalid price (<=0) returns 422 (validation error).
        
        The SKUCreateRequest schema requires price to be > 0.
        FastAPI/Pydantic returns 422 for schema validation failures.
        """
        # Arrange - SKU data with invalid price
        sku_data = {
            "product_id": str(test_product.id),
            "sku_code": "INVALID-PRICE-SKU",
            "price": -10.00,  # Invalid: negative price
            "image_url": "https://example.com/product.jpg",
            "stock_quantity": 10,
        }

        # Act
        response = await client.post(
            "/api/v1/skus",
            json=sku_data,
        )

        # Assert
        assert response.status_code == 422
        
        # Verify error details
        result = response.json()
        # FastAPI returns validation error format
        assert "detail" in result


class TestProductNotFound:
    """Tests for product not found behavior."""

    @pytest.mark.asyncio
    async def test_product_not_found_returns_404(
        self,
        client: AsyncClient,
    ):
        """
        Test that creating a SKU for a non-existent product returns 404.
        
        If the product_id does not exist in the database,
        the endpoint should return 404 Not Found.
        """
        # Arrange - Use a random UUID that doesn't exist
        sku_data = SKUCreateRequest(
            product_id=uuid.uuid4(),
            sku_code="NONEXISTENT-SKU",
            price=99.99,
            image_url="https://example.com/product.jpg",
            stock_quantity=10,
        )

        # Act
        response = await client.post(
            "/api/v1/skus",
            json=sku_data.model_dump(mode="json"),
        )

        # Assert
        assert response.status_code == 404
        
        # Verify error message
        result = response.json()
        assert "not found" in result["message"].lower()