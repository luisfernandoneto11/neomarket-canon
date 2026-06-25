"""
Moderation Apply Service for NeoMarket Moderation.

Handles business logic for applying moderation decisions received from B2B.
Updates product status and manages blocking data based on moderation results.

Idempotency strategy: INSERT event record BEFORE processing the moderation
decision. Since idempotency_key is the PRIMARY KEY of moderation_events table,
concurrent requests with the same key will cause an IntegrityError on the
second INSERT. The service catches this and returns early without side effects.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.moderation_event import ModerationEvent
from models.product import Product
from schemas.moderation_event_schemas import (
    ModerationEventRequest,
    ModerationEventResponse,
)


class ModerationApplyService:
    """
    Service for applying moderation decisions to products.
    
    Handles:
    - Idempotency checks (prevent duplicate processing)
    - Product lookup and validation
    - Status updates (MODERATED or BLOCKED)
    - Blocking data management (reason + field reports)
    """

    async def apply_moderation(
        self,
        session: AsyncSession,
        request: ModerationEventRequest,
    ) -> ModerationEventResponse:
        """
        Apply moderation decision to a product.
        
        Idempotency is enforced by inserting the event record BEFORE processing.
        Since idempotency_key is the PRIMARY KEY, concurrent requests with the
        same key will cause an IntegrityError on the second INSERT.
        
        Args:
            session: Database session.
            request: Moderation event request with decision data.
            
        Returns:
            ModerationEventResponse indicating success.
            
        Raises:
            HTTPException: 404 if product not found.
        """
        # Step 1: Insert event record FIRST (idempotency guard)
        # If another request with same key is being processed concurrently,
        # this INSERT will raise IntegrityError (duplicate PK) and we return early.
        try:
            await self._record_event(session, request)
            await session.flush()  # Flush to trigger PK constraint check
        except IntegrityError:
            # Duplicate idempotency_key — event already processed
            await session.rollback()
            return ModerationEventResponse(ok=True)

        # Step 2: Find product
        product = await self._get_product(session, request.product_id)
        if product is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Product {request.product_id} not found",
            )

        # Step 3: Apply decision based on status
        if request.status == "MODERATED":
            await self._apply_moderated(session, product)
        elif request.status == "BLOCKED":
            await self._apply_blocked(
                session,
                product,
                hard_block=request.hard_block,
                blocking_reason=request.blocking_reason,
                field_reports=request.field_reports,
            )

        await session.commit()

        return ModerationEventResponse(ok=True)

    async def _get_product(
        self,
        session: AsyncSession,
        product_id: uuid.UUID,
    ) -> Optional[Product]:
        """
        Get product by ID.
        
        Args:
            session: Database session.
            product_id: Product UUID.
            
        Returns:
            Product instance or None if not found.
        """
        query = select(Product).where(Product.id == product_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _apply_moderated(
        self,
        session: AsyncSession,
        product: Product,
    ) -> None:
        """
        Apply MODERATED status to product.
        
        - Sets status to MODERATED
        - Clears blocking_reason and field_reports
        
        Args:
            session: Database session.
            product: Product to update.
        """
        product.status = "MODERATED"
        product.blocking_reason = None
        product.field_reports = []

    async def _apply_blocked(
        self,
        session: AsyncSession,
        product: Product,
        hard_block: bool,
        blocking_reason: "BlockingReason",
        field_reports: Optional[list["FieldReport"]],
    ) -> None:
        """
        Apply BLOCKED status to product.
        
        - Sets status to BLOCKED (or HARD_BLOCKED if hard_block=True)
        - Saves blocking_reason (mandatory for both soft and hard blocks)
        - Saves field_reports only for soft blocks (hard blocks may have empty reports)
        
        Args:
            session: Database session.
            product: Product to update.
            hard_block: Whether this is a permanent block.
            blocking_reason: Reason for blocking (mandatory).
            field_reports: List of field validation issues (required for soft blocks only).
        """
        # Determine final status
        if hard_block:
            product.status = "HARD_BLOCKED"
        else:
            product.status = "BLOCKED"

        # Save blocking reason as JSON (mandatory for both soft and hard blocks)
        product.blocking_reason = {
            "id": blocking_reason.id,
            "title": blocking_reason.title,
            "comment": blocking_reason.comment,
        }

        # Save field reports as JSON array (only for soft blocks)
        if field_reports and len(field_reports) > 0:
            product.field_reports = [
                {
                    "field_name": report.field_name,
                    "sku_id": report.sku_id,
                    "comment": report.comment,
                }
                for report in field_reports
            ]
        else:
            product.field_reports = []

    async def _record_event(
        self,
        session: AsyncSession,
        request: ModerationEventRequest,
    ) -> None:
        """
        Record moderation event for idempotency tracking.
        
        Args:
            session: Database session.
            request: Original moderation event request.
        """
        event = ModerationEvent(
            idempotency_key=request.idempotency_key,
            product_id=request.product_id,
            result={
                "status": request.status,
                "hard_block": request.hard_block,
                "blocking_reason": (
                    {
                        "id": request.blocking_reason.id,
                        "title": request.blocking_reason.title,
                        "comment": request.blocking_reason.comment,
                    }
                    if request.blocking_reason
                    else None
                ),
                "field_reports": (
                    [
                        {
                            "field_name": report.field_name,
                            "sku_id": report.sku_id,
                            "comment": report.comment,
                        }
                        for report in request.field_reports
                    ]
                    if request.field_reports
                    else []
                ),
            },
        )
        session.add(event)


# Singleton instance
moderation_apply_service = ModerationApplyService()