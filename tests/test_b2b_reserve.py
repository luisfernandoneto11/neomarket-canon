"""
Tests for Stock Reservation API endpoints.

Tests the POST /api/v1/reserve and POST /api/v1/unreserve endpoints for:
- Happy path: active_quantity decreases, reserved_quantity increases
- Partial insufficient stock returns 409 and rolls back all reservations
- Idempotent reserve returns 200 without double deduction
- SKU_OUT_OF_STOCK event emitted when active_quantity reaches 0
- Unreserve restores active_quantity and reserved_quantity
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.product import SKU, ReserveOperation
from models.database import get_async_session


# Helper to bypass service key auth in tests
def override_service_key():
    """Override the service key verification to always pass."""
    return "test-service-key-123"


class TestReserveStock:
    """Tests for POST /api/v1/reserve endpoint."""

    @pytest.mark.asyncio
    async def test_reserve_all_skus_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        app,
    ):
        """
        Test happy path: active_quantity decreases, reserved_quantity increases.
        
        When all SKUs have sufficient stock, the reserve endpoint should:
        - Return 200 status
        - Return reserved=True
        - Show reserved_quantity for each item
        - Show remaining_stock (active_quantity after reservation)
        """
        # Arrange - Create SKUs with stock
        from fastapi import FastAPI
        from apis.b2b.reserve import router as reserve_router
        
        # Override service key auth
        from apis.b2b import reserve as reserve_module
        original_verify = reserve_module.verify_service_key
        reserve_module.verify_service_key = lambda: "test-service-key-123"
        
        sku1_id = str(uuid.uuid4())
        sku2_id = str(uuid.uuid4())
        
        sku1 = SKU(
            id=sku1_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU001",
            price=99.99,
            on_hand=100,
            active_quantity=100,
            reserved_quantity=0,
        )
        sku2 = SKU(
            id=sku2_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU002",
            price=149.99,
            on_hand=50,
            active_quantity=50,
            reserved_quantity=0,
        )
        db_session.add_all([sku1, sku2])
        await db_session.commit()
        
        reserve_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [
                {"sku_id": sku1_id, "quantity": 30},
                {"sku_id": sku2_id, "quantity": 20},
            ],
        }
        
        # Act
        response = await client.post("/api/v1/reserve", json=reserve_payload)
        
        # Assert
        assert response.status_code == 200
        
        result = response.json()
        assert result["reserved"] is True
        assert len(result["items"]) == 2
        
        # Check first item
        item1 = next(i for i in result["items"] if i["sku_id"] == sku1_id)
        assert item1["reserved_quantity"] == 30
        assert item1["remaining_stock"] == 70  # 100 - 30
        
        # Check second item
        item2 = next(i for i in result["items"] if i["sku_id"] == sku2_id)
        assert item2["reserved_quantity"] == 20
        assert item2["remaining_stock"] == 30  # 50 - 20
        
        # Verify database state
        await db_session.refresh(sku1)
        await db_session.refresh(sku2)
        assert sku1.active_quantity == 70
        assert sku1.reserved_quantity == 30
        assert sku2.active_quantity == 30
        assert sku2.reserved_quantity == 20

    @pytest.mark.asyncio
    async def test_partial_insufficient_stock_returns_409_all_rollback(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that if one SKU has insufficient stock, returns 409 and nothing is reserved.
        
        When any SKU has insufficient stock:
        - Return 409 status
        - Return reserved=False
        - Include failed_items with reason
        - Rollback all reservations (nothing changed in DB)
        """
        # Arrange - Create SKUs where one has insufficient stock
        from apis.b2b import reserve as reserve_module
        reserve_module.verify_service_key = lambda: "test-service-key-123"
        
        sku1_id = str(uuid.uuid4())
        sku2_id = str(uuid.uuid4())
        
        sku1 = SKU(
            id=sku1_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU003",
            price=99.99,
            on_hand=100,
            active_quantity=100,
            reserved_quantity=0,
        )
        sku2 = SKU(
            id=sku2_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU004",
            price=149.99,
            on_hand=5,  # Only 5 available
            active_quantity=5,
            reserved_quantity=0,
        )
        db_session.add_all([sku1, sku2])
        await db_session.commit()
        
        reserve_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [
                {"sku_id": sku1_id, "quantity": 30},  # This would succeed alone
                {"sku_id": sku2_id, "quantity": 20},  # This exceeds stock
            ],
        }
        
        # Act
        response = await client.post("/api/v1/reserve", json=reserve_payload)
        
        # Assert
        assert response.status_code == 409
        
        result = response.json()
        # The response is wrapped in HTTPException detail
        detail = result.get("detail", result)
        assert detail["reserved"] is False
        assert len(detail["failed_items"]) == 1
        assert detail["failed_items"][0]["sku_id"] == sku2_id
        assert "Insufficient stock" in detail["failed_items"][0]["reason"]
        
        # Verify database was NOT modified (rollback)
        await db_session.refresh(sku1)
        await db_session.refresh(sku2)
        assert sku1.active_quantity == 100  # Unchanged
        assert sku1.reserved_quantity == 0  # Unchanged
        assert sku2.active_quantity == 5  # Unchanged
        assert sku2.reserved_quantity == 0  # Unchanged

    @pytest.mark.asyncio
    async def test_idempotent_reserve_returns_200_without_double_deduction(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that same idempotency_key returns 200 without double deduction.
        
        When a request with the same idempotency_key is made:
        - Return 200 with cached response
        - No additional stock deduction
        - Database state unchanged
        """
        # Arrange
        from apis.b2b import reserve as reserve_module
        reserve_module.verify_service_key = lambda: "test-service-key-123"
        
        sku_id = str(uuid.uuid4())
        idempotency_key = str(uuid.uuid4())
        
        sku = SKU(
            id=sku_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU005",
            price=99.99,
            on_hand=100,
            active_quantity=100,
            reserved_quantity=0,
        )
        db_session.add(sku)
        await db_session.commit()
        
        reserve_payload = {
            "idempotency_key": idempotency_key,
            "items": [{"sku_id": sku_id, "quantity": 30}],
        }
        
        # Act - First request
        response1 = await client.post("/api/v1/reserve", json=reserve_payload)
        assert response1.status_code == 200
        
        first_result = response1.json()
        assert first_result["reserved"] is True
        
        # Refresh and record state after first reservation
        await db_session.refresh(sku)
        first_active = sku.active_quantity
        first_reserved = sku.reserved_quantity
        
        # Act - Second request with same idempotency_key
        response2 = await client.post("/api/v1/reserve", json=reserve_payload)
        
        # Assert
        assert response2.status_code == 200
        second_result = response2.json()
        assert second_result["reserved"] is True
        
        # Verify no double deduction
        await db_session.refresh(sku)
        assert sku.active_quantity == first_active  # Unchanged
        assert sku.reserved_quantity == first_reserved  # Unchanged

    @pytest.mark.asyncio
    async def test_sku_out_of_stock_event_emitted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that SKU_OUT_OF_STOCK event is emitted when active_quantity reaches 0.
        
        When a reservation causes active_quantity to become 0:
        - Return 200 (reservation successful)
        - Emit SKU_OUT_OF_STOCK event to B2C catalog
        """
        # Arrange
        from apis.b2b import reserve as reserve_module
        reserve_module.verify_service_key = lambda: "test-service-key-123"
        
        sku_id = str(uuid.uuid4())
        
        sku = SKU(
            id=sku_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU006",
            price=99.99,
            on_hand=30,
            active_quantity=30,
            reserved_quantity=0,
        )
        db_session.add(sku)
        await db_session.commit()
        
        reserve_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku_id": sku_id, "quantity": 30}],  # Reserve all stock
        }
        
        # Act - Patch the event emission method
        with patch("apis.b2b.reserve.ReserveService._emit_out_of_stock_event", new_callable=AsyncMock) as mock_emit:
            # We need to patch in the service module, not the API module
            with patch("services.reserve_service.ReserveService._emit_out_of_stock_event", new_callable=AsyncMock) as mock_emit_service:
                response = await client.post("/api/v1/reserve", json=reserve_payload)
                
                # Assert
                assert response.status_code == 200
                result = response.json()
                assert result["reserved"] is True
                
                # Verify event was emitted
                mock_emit_service.assert_called_once()
                
                # Verify quantity is 0
                await db_session.refresh(sku)
                assert sku.active_quantity == 0
                assert sku.reserved_quantity == 30

    @pytest.mark.asyncio
    async def test_unreserve_restores_quantities(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """
        Test that unreserve restores active_quantity and reserved_quantity.
        
        When unreserve is called:
        - Return 200 with ok=True
        - active_quantity increases
        - reserved_quantity decreases
        """
        # Arrange - Create SKU with reserved stock
        from apis.b2b import reserve as reserve_module
        reserve_module.verify_service_key = lambda: "test-service-key-123"
        
        sku_id = str(uuid.uuid4())
        
        sku = SKU(
            id=sku_id,
            product_id=str(uuid.uuid4()),
            sku_code="SKU007",
            price=99.99,
            on_hand=100,
            active_quantity=50,
            reserved_quantity=50,
        )
        db_session.add(sku)
        await db_session.commit()
        
        unreserve_payload = {
            "order_id": str(uuid.uuid4()),
            "items": [{"sku_id": sku_id, "quantity": 30}],
        }
        
        # Act
        response = await client.post("/api/v1/unreserve", json=unreserve_payload)
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        
        # Verify database state
        await db_session.refresh(sku)
        assert sku.active_quantity == 80  # 50 + 30
        assert sku.reserved_quantity == 20  # 50 - 30


class TestReserveEndpointAuth:
    """Tests for authentication on reserve endpoints."""

    @pytest.mark.asyncio
    async def test_reserve_without_service_key_returns_401(
        self,
        client: AsyncClient,
    ):
        """
        Test that reserve endpoint returns 401 without X-Service-Key header.
        """
        reserve_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku_id": str(uuid.uuid4()), "quantity": 1}],
        }
        
        response = await client.post("/api/v1/reserve", json=reserve_payload)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_reserve_with_invalid_service_key_returns_401(
        self,
        client: AsyncClient,
    ):
        """
        Test that reserve endpoint returns 401 with invalid X-Service-Key.
        """
        reserve_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku_id": str(uuid.uuid4()), "quantity": 1}],
        }
        
        response = await client.post(
            "/api/v1/reserve",
            json=reserve_payload,
            headers={"X-Service-Key": "invalid-key"},
        )
        assert response.status_code == 401