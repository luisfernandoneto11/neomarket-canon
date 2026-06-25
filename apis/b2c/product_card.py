"""
B2C Product Card API Router.

Provides the endpoint for fetching individual product details
for buyers viewing a product detail page.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from services.product_card_service import ProductCardService, ProductNotVisibleError
from schemas.product_card_schemas import ProductCardResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["B2C - Product Card"],
)


@router.get(
    "/api/v1/products/{product_id}",
    response_model=ProductCardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get product card",
    description="Fetch full product details by ID for the B2C product page. Returns product data without sensitive fields (cost_price, reserved_quantity).",
    responses={
        200: {"description": "Product card retrieved successfully"},
        404: {"description": "Product not found or not visible"},
        502: {"description": "B2B service temporarily unavailable"},
    },
)
async def get_product_card(product_id: str) -> ProductCardResponse:
    """
    Get product card by ID.
    
    Fetches product details from B2B, validates visibility,
    strips sensitive fields, and returns B2C-safe data.
    """
    service = ProductCardService()

    try:
        return await service.get_product_card(str(product_id))
    except ProductNotVisibleError as e:
        logger.warning(f"Product {product_id} not visible: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PRODUCT_NOT_FOUND",
                "message": "Product not found or no longer available",
            },
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching product card {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "B2B_UNAVAILABLE",
                "message": "Unable to fetch product data. Please try again later.",
            },
        )