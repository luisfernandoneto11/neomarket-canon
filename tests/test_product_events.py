"""
Tests for POST /api/v1/b2b/events endpoint.

Tests product event processing from B2B service.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from models.product_moderation import ProductModeration


class TestProductCreatedEvent:
    """Test CREATED event processing."""

    @pytest.mark.asyncio
    async def test_created_pending(
        self,
        client: AsyncClient,
        db_session,
        sample_product_data: dict,
        service_key: str,
    ):
        """
        Test that CREATED event creates a PENDING moderation record.
        
        Given: Product does not exist in moderation
        When: CREATED event is received
        Then: New PENDING record is created with queue_priority=1
        """
        product_id = uuid.uuid4()
        seller_id = uuid.uuid4()
        event_date = datetime.utcnow()
        idempotency_key = uuid.uuid4()
        
        response = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "event_type": "PRODUCT_CREATED",
                "occurred_at": event_date.isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": sample_product_data,
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Assert response
        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        assert "created and queued" in data["message"]
        assert data["moderation_id"] is not None
        assert data["queue_priority"] == 1
        
        # Verify database record
        query = select(ProductModeration).where(
            ProductModeration.product_id == product_id
        )
        result = await db_session.execute(query)
        moderation = result.scalar_one_or_none()
        
        assert moderation is not None
        assert moderation.status == "PENDING"
        assert moderation.queue_priority == 1
        assert moderation.json_before is None  # No previous state for new products
        assert moderation.json_after == sample_product_data
        assert moderation.seller_id == seller_id
        assert moderation.idempotency_key == idempotency_key


class TestProductEditedEvent:
    """Test EDITED event processing."""

    @pytest.mark.asyncio
    async def test_edited_returns_to_review(
        self,
        client: AsyncClient,
        db_session,
        moderated_product: ProductModeration,
        mock_b2b_product: dict,
        service_key: str,
    ):
        """
        Test that EDITED event after MODERATED/BLOCKED returns product to PENDING.
        
        Given: Product was previously MODERATED
        When: EDITED event is received
        Then: Record is updated to PENDING with new data
        """
        original_moderation_id = moderated_product.id
        original_date_moderation = moderated_product.date_moderation
        idempotency_key = uuid.uuid4()
        
        response = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(moderated_product.product_id),
                "seller_id": str(moderated_product.seller_id),
                "event_type": "PRODUCT_EDITED",
                "occurred_at": datetime.utcnow().isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": mock_b2b_product,
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Assert response
        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        assert "re-queued" in data["message"]
        assert data["moderation_id"] == str(original_moderation_id)
        
        # Verify database record
        # Refresh the session to get updated data from DB
        db_session.expire_all()
        query = select(ProductModeration).where(
            ProductModeration.id == original_moderation_id
        )
        result = await db_session.execute(query)
        moderation = result.scalar_one()
        
        assert moderation.status == "PENDING"
        assert moderation.json_before is not None  # Previous state preserved
        assert moderation.json_after == mock_b2b_product
        assert moderation.blocking_reason_id is None  # Cleared
        assert moderation.moderator_id is None  # Cleared
        assert moderation.moderator_comment is None  # Cleared
        assert moderation.date_moderation is None  # Cleared

    @pytest.mark.asyncio
    async def test_edited_updates_in_review(
        self,
        client: AsyncClient,
        db_session,
        in_review_product: ProductModeration,
        mock_b2b_product: dict,
        service_key: str,
    ):
        """
        Test that EDITED event during IN_REVIEW updates fields.
        
        Given: Product is currently IN_REVIEW
        When: EDITED event is received
        Then: Record is updated with new data, status returns to PENDING
        """
        original_moderation_id = in_review_product.id
        original_moderator = in_review_product.moderator_id
        idempotency_key = uuid.uuid4()
        
        response = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(in_review_product.product_id),
                "seller_id": str(in_review_product.seller_id),
                "event_type": "PRODUCT_EDITED",
                "occurred_at": datetime.utcnow().isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": mock_b2b_product,
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Assert response
        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        
        # Verify database record
        # Refresh the session to get updated data from DB
        db_session.expire_all()
        query = select(ProductModeration).where(
            ProductModeration.id == original_moderation_id
        )
        result = await db_session.execute(query)
        moderation = result.scalar_one()
        
        assert moderation.status == "PENDING"
        assert moderation.json_before == {"title": "New Title"}  # Previous state (was json_after before edit)
        assert moderation.json_after == mock_b2b_product
        # Moderator info should be cleared for re-moderation
        assert moderation.moderator_id is None


class TestProductDeletedEvent:
    """Test DELETED event processing."""

    @pytest.mark.asyncio
    async def test_deleted_archived(
        self,
        client: AsyncClient,
        db_session,
        moderated_product: ProductModeration,
        service_key: str,
    ):
        """
        Test that DELETED event removes the moderation record.
        
        Given: Product exists in moderation
        When: DELETED event is received
        Then: Record is deleted from database
        """
        product_id = moderated_product.product_id
        idempotency_key = uuid.uuid4()
        
        response = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(product_id),
                "seller_id": str(moderated_product.seller_id),
                "event_type": "PRODUCT_DELETED",
                "occurred_at": datetime.utcnow().isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": {},
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Assert response
        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        assert "deleted" in data["message"]
        
        # Verify record is deleted
        query = select(ProductModeration).where(
            ProductModeration.product_id == product_id
        )
        result = await db_session.execute(query)
        moderation = result.scalar_one_or_none()
        
        assert moderation is None


class TestIdempotency:
    """Test event idempotency."""

    @pytest.mark.asyncio
    async def test_duplicate_event_no_side_effects(
        self,
        client: AsyncClient,
        db_session,
        sample_product_data: dict,
        service_key: str,
    ):
        """
        Test that duplicate events are idempotent (no side effects).
        
        Given: Event was already processed
        When: Same event is received again
        Then: Returns 202 with idempotent message, no changes
        """
        product_id = uuid.uuid4()
        seller_id = uuid.uuid4()
        event_date = datetime.utcnow()
        idempotency_key = uuid.uuid4()
        
        # First request
        response1 = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "event_type": "PRODUCT_CREATED",
                "occurred_at": event_date.isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": sample_product_data,
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Get moderation_id from first response
        data1 = response1.json()
        moderation_id = data1["moderation_id"]
        
        # Second request (duplicate - same idempotency_key)
        response2 = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "event_type": "PRODUCT_CREATED",
                "occurred_at": event_date.isoformat() + "Z",
                "idempotency_key": str(idempotency_key),
                "payload": {
                    "json_after": sample_product_data,
                },
            },
            headers={"X-Service-Key": service_key},
        )
        
        # Assert both responses are successful
        assert response1.status_code == 202
        assert response2.status_code == 202
        
        # Second response should indicate idempotent
        data2 = response2.json()
        assert data2["success"] is True
        assert "idempotent" in data2["message"]
        
        # Verify only one record exists
        query = select(ProductModeration).where(
            ProductModeration.product_id == product_id
        )
        result = await db_session.execute(query)
        moderations = result.scalars().all()
        
        assert len(moderations) == 1
        assert str(moderations[0].id) == moderation_id


class TestAuthentication:
    """Test authentication and authorization."""

    @pytest.mark.asyncio
    async def test_missing_service_header_401(
        self,
        client: AsyncClient,
    ):
        """
        Test that missing X-Service-Key header returns 401.
        
        Given: Request without X-Service-Key header
        When: POST /api/v1/b2b/events is called
        Then: Returns 401 Unauthorized
        """
        response = await client.post(
            "/api/v1/b2b/events",
            json={
                "product_id": str(uuid.uuid4()),
                "seller_id": str(uuid.uuid4()),
                "event_type": "PRODUCT_CREATED",
                "occurred_at": datetime.utcnow().isoformat() + "Z",
                "idempotency_key": str(uuid.uuid4()),
                "payload": {
                    "json_after": {},
                },
            },
            # No X-Service-Key header
        )
        
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 401
        assert "Invalid service key" in data["message"]
