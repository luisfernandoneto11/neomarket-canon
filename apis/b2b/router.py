"""
B2B API router for product and SKU management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from schemas.b2b_schemas import SKUCreateRequest, SKUResponse
from services.b2b_service import (
    B2BService,
    ProductNotFoundError,
    ProductHardBlockedError,
    DuplicateSKUCodeError,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["B2B - SKUs"],
)


@router.post(
    "/skus",
    response_model=SKUResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new SKU",
    description="Add a new product variant (SKU) to an existing product.",
    responses={
        201: {"description": "SKU created successfully"},
        400: {"description": "Invalid request data"},
        403: {"description": "Product is HARD_BLOCKED"},
        404: {"description": "Product not found"},
        409: {"description": "SKU code already exists"},
        422: {"description": "Schema validation failed"},
    },
)
async def create_sku(
    sku_data: SKUCreateRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SKUResponse:
    """
    Create a new SKU for a product.
    
    This endpoint adds a new product variant (SKU) to an existing product.
    The SKU code must be unique across all products and will be converted to uppercase.
    
    Args:
        sku_data: SKU creation request data
        session: Database session
        
    Returns:
        SKUResponse: Created SKU data
        
    Raises:
        HTTPException 403: If product is HARD_BLOCKED
        HTTPException 404: If product not found
        HTTPException 409: If SKU code already exists
        HTTPException 422: If schema validation fails
    """
    service = B2BService(session)
    
    try:
        result = await service.create_sku(sku_data)
        return result
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ProductHardBlockedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except DuplicateSKUCodeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
