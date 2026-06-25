"""
Orders API Router.

Handles B2C order operations including order cancellation.
"""

import logging
import os
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.database import get_session
from models.order_models import Order, OrderItem, OrderStatus
from schemas.order_schemas import CancelOrderResponse
from schemas.reserve_schemas import UnreserveRequest, UnreserveItem
from services.checkout_service import CheckoutService
from clients.b2b_client import B2BClient, B2BClientError, B2BServiceUnavailableError

router = APIRouter(prefix="/orders", tags=["Orders"])

# Allow cancellable statuses
CANCELLABLE_STATUSES = {OrderStatus.CREATED, OrderStatus.PAID}

logger = logging.getLogger(__name__)


@router.post(
    "/{order_id}/cancel",
    response_model=CancelOrderResponse,
    summary="Cancel an order",
    description="""
    Cancel an order by its ID. Only orders with status CREATED or PAID can be cancelled.
    
    If B2B unreserve succeeds → CANCELLED
    If B2B unreserve fails → CANCEL_PENDING (async retry)
    """,
    responses={
        200: {"description": "Order cancelled successfully"},
        404: {"description": "Order not found or belongs to another user"},
        409: {"description": "Cannot cancel order in current status"},
    },
)
async def cancel_order(
    order_id: UUID,
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CancelOrderResponse:
    """
    Cancel an order.
    
    Flow:
    1. Find order by ID
    2. Validate order exists and belongs to user (IDOR protection)
    3. Validate order status is cancellable (CREATED or PAID)
    4. Call B2B unreserve for all items
    5. Update order status to CANCELLED or CANCEL_PENDING
    
    Args:
        order_id: Order UUID to cancel.
        user_id: User UUID for verification.
        session: Database session.
    
    Returns:
        CancelOrderResponse with updated status.
    
    Raises:
        HTTPException 404: Order not found or belongs to another user.
        HTTPException 409: Order status does not allow cancellation.
    """
    # Step 1: Find order by ID with items loaded
    query = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    result = await session.execute(query)
    order = result.scalars().first()
    
    # Step 2: Validate order exists and belongs to user (IDOR: return 404, not 403)
    if order is None or str(order.user_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    
    # Step 3: Validate order status is cancellable
    if order.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CANCEL_NOT_ALLOWED",
        )
    
    # Step 4: Call B2B unreserve for all items
    b2b_base_url = os.getenv("B2B_SERVICE_URL", "http://localhost:8001")
    b2b_service_key = os.getenv("B2B_SERVICE_KEY", "b2b-service-secret-key")
    
    b2b_client = B2BClient(
        base_url=b2b_base_url,
        service_key=b2b_service_key,
    )
    
    unreserve_items = [
        UnreserveItem(sku_id=str(item.sku_id), quantity=item.quantity)
        for item in order.items
    ]
    
    unreserve_request = UnreserveRequest(
        order_id=str(order_id),
        items=unreserve_items,
    )
    
    try:
        await b2b_client.unreserve(unreserve_request)
        # B2B success: order is cancelled
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()
        await session.commit()
        
        return CancelOrderResponse(
            id=order.id,
            status=order.status.value,
            message="Order cancelled successfully",
        )
    except B2BServiceUnavailableError as e:
        # B2B timeout/unavailable: mark as CANCEL_PENDING for async retry
        logger.warning(f"B2B unreserve unavailable for order {order_id}: {e}")
        order.status = OrderStatus.CANCEL_PENDING
        order.cancel_pending_since = datetime.utcnow()
        order.updated_at = datetime.utcnow()
        await session.commit()
        
        return CancelOrderResponse(
            id=order.id,
            status=order.status.value,
            message="Cancellation pending - B2B service unavailable, retrying",
        )
    except B2BClientError as e:
        # B2B client error (4xx): also mark as CANCEL_PENDING
        logger.warning(f"B2B unreserve failed for order {order_id}: {e}")
        order.status = OrderStatus.CANCEL_PENDING
        order.cancel_pending_since = datetime.utcnow()
        order.updated_at = datetime.utcnow()
        await session.commit()
        
        return CancelOrderResponse(
            id=order.id,
            status=order.status.value,
            message=f"Cancellation pending - B2B unreserve failed: {str(e)}",
        )
