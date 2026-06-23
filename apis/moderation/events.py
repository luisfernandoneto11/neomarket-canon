"""
Product Events Endpoint for NeoMarket Moderation Service.

Handles POST /api/v1/b2b/events endpoint for receiving
product events from B2B service.
"""

import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from services.product_event_service import (
    check_idempotency,
    fetch_product_from_b2b,
    process_created_event,
    process_deleted_event,
    process_edited_event,
)

router = APIRouter(prefix="/api/v1/b2b", tags=["Events"])

# Configuration
B2B_SERVICE_KEY = os.getenv("B2B_SERVICE_KEY", "your-secret-key-here")


# Request/Response Models
class ProductEventRequest(BaseModel):
    """Request model for product events from B2B."""
    
    product_id: uuid.UUID = Field(..., description="Product UUID")
    seller_id: uuid.UUID = Field(..., description="Seller UUID")
    event_type: str = Field(
        ...,
        description="Event type: PRODUCT_CREATED, PRODUCT_EDITED, or PRODUCT_DELETED",
        regex="^(PRODUCT_CREATED|PRODUCT_EDITED|PRODUCT_DELETED)$",
    )
    occurred_at: datetime = Field(..., description="Event timestamp in ISO8601 format")
    idempotency_key: uuid.UUID = Field(..., description="Unique key for idempotency")
    
    class Config:
        json_schema_extra = {
            "example": {
                "product_id": "12345678-1234-5678-1234-567812345678",
                "seller_id": "87654321-4321-8765-4321-876543210987",
                "event_type": "PRODUCT_CREATED",
                "occurred_at": "2024-01-15T10:30:00Z",
                "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            }
        }


class ProductEventResponse(BaseModel):
    """Response model for product events."""
    
    success: bool = Field(..., description="Whether event was processed successfully")
    message: str = Field(..., description="Response message")
    moderation_id: Optional[uuid.UUID] = Field(
        None, description="Moderation record ID (if applicable)"
    )
    queue_priority: Optional[int] = Field(
        None, description="Queue priority (1-4, if applicable)"
    )


# Authentication Dependency
async def verify_service_key(
    x_service_key: str = Header(..., alias="X-Service-Key"),
) -> str:
    """
    Verify the X-Service-Key header for service-to-service authentication.
    
    Args:
        x_service_key: Service key from header.
        
    Returns:
        Validated service key.
        
    Raises:
        HTTPException: If service key is invalid.
    """
    if x_service_key != B2B_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service key",
        )
    return x_service_key


# Event Processing Endpoint
@router.post(
    "/events",
    response_model=ProductEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive product event from B2B",
    description="""
    Receive product events (CREATED, EDITED, DELETED) from B2B service.
    
    This endpoint processes product events and manages moderation records:
    - **PRODUCT_CREATED**: Creates new PENDING moderation record with queue_priority=1
    - **PRODUCT_EDITED**: Updates existing record, recalculates queue_priority, clears field reports
    - **PRODUCT_DELETED**: Removes moderation record
    
    Idempotency is ensured by (product_id, occurred_at) combination.
    """,
)
async def receive_product_event(
    event_data: ProductEventRequest,
    session: AsyncSession = Depends(get_async_session),
    service_key: str = Depends(verify_service_key),
) -> ProductEventResponse:
    """
    Process product event from B2B service.
    
    Args:
        event_data: Product event data.
        session: Database session.
        service_key: Verified service key.
        
    Returns:
        Response indicating success/failure.
    """
    try:
        # Check idempotency - skip if already processed
        is_duplicate = await check_idempotency(
            session, event_data.idempotency_key
        )
        
        if is_duplicate:
            return ProductEventResponse(
                success=True,
                message="Event already processed (idempotent)",
            )
        
        # Process based on event type
        if event_data.event_type == "PRODUCT_CREATED":
            return await _handle_created_event(session, event_data)
        elif event_data.event_type == "PRODUCT_EDITED":
            return await _handle_edited_event(session, event_data)
        elif event_data.event_type == "PRODUCT_DELETED":
            return await _handle_deleted_event(session, event_data)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid event type: {event_data.event_type}",
            )
    
    except HTTPException:
        await session.rollback()
        raise
    except NotImplementedError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(e),
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error processing event: {str(e)}",
        )


async def _handle_created_event(
    session: AsyncSession,
    event_data: ProductEventRequest,
) -> ProductEventResponse:
    """Handle CREATED event."""
    # Fetch product data from B2B
    product_data = await fetch_product_from_b2b(event_data.product_id)
    
    if product_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {event_data.product_id} not found in B2B",
        )
    
    # Process created event
    moderation = await process_created_event(
        session,
        event_data.product_id,
        event_data.seller_id,
        product_data,
        event_data.idempotency_key,
    )
    
    await session.commit()
    
    return ProductEventResponse(
        success=True,
        message="Product created and queued for moderation",
        moderation_id=moderation.id,
        queue_priority=moderation.queue_priority,
    )


async def _handle_edited_event(
    session: AsyncSession,
    event_data: ProductEventRequest,
) -> ProductEventResponse:
    """Handle EDITED event."""
    # Fetch updated product data from B2B
    product_data = await fetch_product_from_b2b(event_data.product_id)
    
    if product_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {event_data.product_id} not found in B2B",
        )
    
    # Process edited event
    moderation = await process_edited_event(
        session,
        event_data.product_id,
        event_data.seller_id,
        product_data,
        event_data.idempotency_key,
    )
    
    await session.commit()
    
    return ProductEventResponse(
        success=True,
        message="Product updated and re-queued for moderation",
        moderation_id=moderation.id,
        queue_priority=moderation.queue_priority,
    )


async def _handle_deleted_event(
    session: AsyncSession,
    event_data: ProductEventRequest,
) -> ProductEventResponse:
    """Handle DELETED event."""
    # Process deleted event
    deleted = await process_deleted_event(session, event_data.product_id)
    
    await session.commit()
    
    if deleted:
        return ProductEventResponse(
            success=True,
            message="Product moderation record deleted",
        )
    else:
        return ProductEventResponse(
            success=True,
            message="No moderation record found (already deleted or never existed)",
        )
