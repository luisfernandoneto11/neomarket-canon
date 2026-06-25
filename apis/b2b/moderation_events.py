"""
Moderation Events API for B2B integration.

Handles moderation decision webhooks from B2B service.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from schemas.moderation_event_schemas import (
    ModerationEventRequest,
    ModerationEventResponse,
)
from services.moderation_apply_service import moderation_apply_service

router = APIRouter(
    prefix="/api/v1/events",
    tags=["Moderation Events"],
)

# Service key for authentication
VALID_SERVICE_KEY = "b2b-service-key-2024"


@router.post(
    "/moderation",
    response_model=ModerationEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Process moderation decision",
    description="Receives moderation decision from B2B and applies it to the product.",
    responses={
        200: {"description": "Moderation decision applied successfully"},
        400: {"description": "Invalid request data"},
        401: {"description": "Invalid or missing X-Service-Key header"},
        404: {"description": "Product not found"},
    },
)
async def process_moderation_event(
    request: ModerationEventRequest,
    session: AsyncSession = Depends(get_async_session),
    x_service_key: str = Header(
        ...,
        alias="X-Service-Key",
        description="Service key for authentication",
    ),
) -> ModerationEventResponse:
    """
    Process moderation decision from B2B.
    
    This webhook receives moderation results (MODERATED or BLOCKED)
    and updates the product status accordingly.
    
    Args:
        request: Moderation event request with decision data.
        session: Database session.
        x_service_key: Authentication header.
        
    Returns:
        ModerationEventResponse indicating success.
        
    Raises:
        HTTPException 401: If X-Service-Key is invalid.
        HTTPException 404: If product not found.
        HTTPException 400: If request data is invalid.
    """
    # Validate service key
    if x_service_key != VALID_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Service-Key",
        )

    try:
        # Call moderation apply service
        return await moderation_apply_service.apply_moderation(session, request)
    except HTTPException:
        # Re-raise HTTP exceptions (404, etc.)
        raise
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process moderation event: {str(e)}",
        )