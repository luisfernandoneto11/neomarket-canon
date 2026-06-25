"""
Stock Reservation API endpoints for NeoMarket B2B service.

Provides endpoints for stock reservation and unreservation operations
with idempotency support and service-to-service authentication.
"""

import os
from typing import Union

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from schemas.reserve_schemas import (
    ReserveRequest,
    ReserveResponse,
    ReserveErrorResponse,
    UnreserveRequest,
    UnreserveResponse,
)
from services.reserve_service import ReserveService

router = APIRouter(
    prefix="/api/v1",
    tags=["B2B - Stock Reservation"],
)

# Configuration
B2B_SERVICE_KEY = os.getenv("B2B_SERVICE_KEY", "your-secret-key-here")


def verify_service_key(
    x_service_key: str = Header(None, alias="X-Service-Key"),
) -> str:
    """
    Verify the X-Service-Key header for service-to-service authentication.
    
    Args:
        x_service_key: Service key from header.
        
    Returns:
        Validated service key.
        
    Raises:
        HTTPException: If service key is missing or invalid.
    """
    if x_service_key is None or x_service_key != B2B_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service key",
        )
    return x_service_key


@router.post(
    "/reserve",
    response_model=ReserveResponse,
    status_code=status.HTTP_200_OK,
    summary="Reserve stock for items",
    description="""
    Reserve stock for one or more SKUs.
    
    This endpoint:
    - Validates stock availability
    - Locks SKUs with SELECT FOR UPDATE
    - Updates active and reserved quantities
    - Supports idempotent requests via idempotency_key
    - Emits SKU_OUT_OF_STOCK events when stock reaches 0
    
    Returns:
    - 200: Successful reservation with details
    - 409: Insufficient stock with failed items list
    - 401: Invalid service key
    """,
    responses={
        200: {"description": "Stock reserved successfully"},
        401: {"description": "Invalid or missing service key"},
        409: {"description": "Insufficient stock for one or more items"},
        422: {"description": "Validation error in request body"},
    },
)
async def reserve_stock(
    request: ReserveRequest,
    session: AsyncSession = Depends(get_async_session),
    service_key: str = Depends(verify_service_key),
) -> Union[ReserveResponse, ReserveErrorResponse]:
    """
    Reserve stock for multiple SKUs.
    
    Args:
        request: Reserve request with idempotency_key and items to reserve.
        session: Database session.
        service_key: Verified service key.
        
    Returns:
        ReserveResponse on success, ReserveErrorResponse on insufficient stock.
        
    Raises:
        HTTPException 401: If service key is invalid.
        HTTPException 409: If stock is insufficient for any item.
    """
    service = ReserveService(session)
    
    result = await service.reserve(request)
    
    # Check if reservation failed due to insufficient stock
    if isinstance(result, ReserveErrorResponse):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.model_dump(mode="json"),
        )
    
    return result


@router.post(
    "/unreserve",
    response_model=UnreserveResponse,
    status_code=status.HTTP_200_OK,
    summary="Unreserve stock for an order",
    description="""
    Release reserved stock back to active inventory.
    
    This endpoint:
    - Validates the request
    - Locks SKUs with SELECT FOR UPDATE
    - Updates reserved and active quantities
    - Commits the transaction
    
    Returns:
    - 200: Stock unreserved successfully
    - 401: Invalid service key
    """,
    responses={
        200: {"description": "Stock unreserved successfully"},
        401: {"description": "Invalid or missing service key"},
        422: {"description": "Validation error in request body"},
    },
)
async def unreserve_stock(
    request: UnreserveRequest,
    session: AsyncSession = Depends(get_async_session),
    service_key: str = Depends(verify_service_key),
) -> UnreserveResponse:
    """
    Unreserve stock for an order.
    
    Args:
        request: Unreserve request with order_id and items to unreserve.
        session: Database session.
        service_key: Verified service key.
        
    Returns:
        UnreserveResponse indicating success.
        
    Raises:
        HTTPException 401: If service key is invalid.
    """
    service = ReserveService(session)
    
    result = await service.unreserve(request)
    
    return result