"""
Stock Reservation Service for NeoMarket.

Handles stock reservation and unreservation operations with idempotency support.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from models.product import SKU, ReserveOperation
from schemas.reserve_schemas import (
    ReserveRequest,
    ReserveResponse,
    ReserveItemResponse,
    ReserveErrorResponse,
    FailedItem,
    UnreserveRequest,
    UnreserveResponse,
)


class ReserveServiceError(Exception):
    """Base exception for reserve service errors."""
    pass


class InsufficientStockError(ReserveServiceError):
    """Raised when there is not enough stock to reserve."""
    pass


class SKUNotFoundError(ReserveServiceError):
    """Raised when a SKU is not found."""
    pass


class ReserveService:
    """
    Service for stock reservation operations.
    
    Handles:
    - Stock reservation with idempotency
    - Stock unreservation
    - SKU_OUT_OF_STOCK event emission
    """
    
    def __init__(self, session: AsyncSession):
        """
        Initialize reserve service.
        
        Args:
            session: Database session.
        """
        self.session = session
    
    async def _check_idempotency(
        self, idempotency_key: str
    ) -> Optional[dict]:
        """
        Check if a reservation was already processed.
        
        Args:
            idempotency_key: Unique key for idempotency.
            
        Returns:
            Cached result if already processed, None otherwise.
        """
        query = select(ReserveOperation).where(
            ReserveOperation.idempotency_key == idempotency_key
        )
        result = await self.session.execute(query)
        existing = result.scalars().first()
        
        if existing and existing.result:
            return json.loads(existing.result)
        return None
    
    async def _save_idempotency(
        self, idempotency_key: str, result: dict
    ) -> None:
        """
        Save idempotency record for a reservation.
        
        Args:
            idempotency_key: Unique key for idempotency.
            result: Result to cache.
        """
        operation = ReserveOperation(
            idempotency_key=idempotency_key,
            result=json.dumps(result, default=str),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(operation)
    
    async def _get_sku_with_lock(
        self, sku_id: str
    ) -> Optional[SKU]:
        """
        Get SKU with SELECT FOR UPDATE lock.
        
        Args:
            sku_id: SKU identifier.
            
        Returns:
            SKU instance or None if not found.
        """
        query = (
            select(SKU)
            .where(SKU.id == sku_id)
            .with_for_update()
        )
        result = await self.session.execute(query)
        return result.scalars().first()
    
    async def reserve(
        self, request: ReserveRequest
    ) -> ReserveResponse:
        """
        Reserve stock for multiple items.
        
        This method:
        1. Checks idempotency (if already processed, returns cached response)
        2. Locks SKUs with SELECT FOR UPDATE
        3. Verifies stock availability
        4. Updates active_quantity and reserved_quantity
        5. Emits SKU_OUT_OF_STOCK event if active_quantity becomes 0
        6. Saves idempotency record
        7. Commits transaction
        
        Args:
            request: Reserve request with items to reserve.
            
        Returns:
            ReserveResponse with reservation details.
            
        Raises:
            InsufficientStockError: If any SKU has insufficient stock.
            SKUNotFoundError: If any SKU is not found.
        """
        # Step 1: Check idempotency
        cached_result = await self._check_idempotency(request.idempotency_key)
        if cached_result:
            return ReserveResponse(**cached_result)
        
        # Step 2: Lock SKUs and verify availability
        items_response = []
        failed_items = []
        sku_updates = {}
        
        for item in request.items:
            sku = await self._get_sku_with_lock(item.sku_id)
            
            if not sku:
                failed_items.append(
                    FailedItem(
                        sku_id=item.sku_id,
                        reason="SKU not found"
                    )
                )
                continue
            
            # Check stock availability
            if sku.active_quantity < item.quantity:
                failed_items.append(
                    FailedItem(
                        sku_id=item.sku_id,
                        reason=f"Insufficient stock. Available: {sku.active_quantity}, Requested: {item.quantity}"
                    )
                )
                continue
            
            # Store update for later
            sku_updates[item.sku_id] = {
                "sku": sku,
                "quantity": item.quantity,
            }
        
        # If any failures, rollback and return error
        if failed_items:
            await self.session.rollback()
            error_response = ReserveErrorResponse(
                reserved=False,
                failed_items=failed_items
            )
            return error_response
        
        # Step 3: Update SKUs
        out_of_stock_skus = []
        for item in request.items:
            update_info = sku_updates[item.sku_id]
            sku = update_info["sku"]
            quantity = update_info["quantity"]
            
            # Update quantities
            sku.active_quantity -= quantity
            sku.reserved_quantity += quantity
            
            # Check if SKU is now out of stock
            if sku.active_quantity == 0:
                out_of_stock_skus.append(sku)
            
            items_response.append(
                ReserveItemResponse(
                    sku_id=item.sku_id,
                    reserved_quantity=quantity,
                    remaining_stock=sku.active_quantity
                )
            )
        
        # Step 4: Emit SKU_OUT_OF_STOCK events
        for sku in out_of_stock_skus:
            await self._emit_out_of_stock_event(sku)
        
        # Step 5: Save idempotency record
        response = ReserveResponse(
            reserved=True,
            items=items_response
        )
        
        await self._save_idempotency(
            request.idempotency_key,
            response.model_dump(mode="json")
        )
        
        # Step 6: Commit transaction
        await self.session.commit()
        
        return response
    
    async def unreserve(
        self, request: UnreserveRequest
    ) -> UnreserveResponse:
        """
        Unreserve stock for an order.
        
        Args:
            request: Unreserve request with order_id and items.
            
        Returns:
            UnreserveResponse indicating success.
        """
        for item in request.items:
            sku = await self._get_sku_with_lock(item.sku_id)
            
            if sku:
                # Release reserved stock back to active
                release_qty = min(item.quantity, sku.reserved_quantity)
                sku.reserved_quantity -= release_qty
                sku.active_quantity += release_qty
        
        await self.session.commit()
        
        return UnreserveResponse(ok=True)
    
    async def _emit_out_of_stock_event(self, sku: SKU) -> None:
        """
        Emit SKU_OUT_OF_STOCK event to B2C catalog.
        
        This event notifies the catalog service that a SKU is out of stock.
        
        Args:
            sku: SKU that is out of stock.
        """
        # TODO: Implement actual event emission (e.g., via message queue)
        # For now, this is a placeholder for the event emission logic
        # In production, this would publish to Kafka/RabbitMQ/etc.
        pass