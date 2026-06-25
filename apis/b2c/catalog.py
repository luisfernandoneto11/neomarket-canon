"""
B2C Catalog API Router for public product listing.

Provides endpoints for browsing the catalog with filters, pagination,
and facet aggregation for frontend filtering UI.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from schemas.catalog_filters_schemas import (
    ProductListQueryParams,
    ProductListResponse,
    FacetResponse,
)
from services.catalog_service import CatalogService
from clients.b2b_client import B2BClient, B2BServiceUnavailableError

import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["B2C - Catalog"],
)

# Valid sort options
VALID_SORTS = {"price_asc", "price_desc", "date_desc", "popularity"}


@router.get(
    "/products",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List products in catalog",
    description="Retrieve a paginated list of products with filtering and sorting.",
    responses={
        200: {"description": "Catalog retrieved successfully"},
        400: {"description": "Invalid filter parameters"},
        502: {"description": "B2B service temporarily unavailable"},
    },
)
async def list_products(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items per page (1-100)",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of items to skip for pagination",
    ),
    category: Optional[str] = Query(
        None,
        description="Filter by category UUID",
    ),
    min_price: Optional[float] = Query(
        None,
        ge=0,
        description="Minimum price filter",
    ),
    max_price: Optional[float] = Query(
        None,
        ge=0,
        description="Maximum price filter",
    ),
    in_stock: Optional[bool] = Query(
        None,
        description="Filter by stock availability",
    ),
    search: Optional[str] = Query(
        None,
        description="Search query for product name/description",
    ),
    sort: Optional[str] = Query(
        None,
        description="Sort order: price_asc, price_desc, date_desc, popularity",
    ),
    session: AsyncSession = Depends(get_async_session),
) -> ProductListResponse:
    """
    List products with filtering and sorting.

    Validates query parameters, then fetches products from the B2B catalog.
    Returns enriched product data with pricing and stock information.
    """
    # Validate sort parameter
    if sort and sort not in VALID_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_SORT",
                "message": "Sort must be one of: price_asc, price_desc, date_desc, popularity",
            },
        )

    # Validate category UUID format
    if category:
        try:
            uuid.UUID(category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_CATEGORY",
                    "message": "category must be a valid UUID",
                },
            )

    # Validate price range
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PRICE_RANGE",
                "message": "min_price cannot be greater than max_price",
            },
        )

    # Build query params
    query_params = ProductListQueryParams(
        limit=limit,
        offset=offset,
        category=category,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        search=search,
        sort=sort,
    )

    service = CatalogService(session=session)

    try:
        result = await service.get_catalog(query_params)
        return result
    except B2BServiceUnavailableError as e:
        logger.error(f"B2B service unavailable during catalog fetch: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "B2B_UNAVAILABLE",
                "message": "Catalog service is temporarily unavailable",
            },
        )


@router.get(
    "/catalog/facets",
    response_model=FacetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get catalog facets",
    description="Returns facet counts for categories, price ranges, and availability.",
    responses={
        200: {"description": "Facets retrieved successfully"},
        400: {"description": "Invalid filter parameters"},
        502: {"description": "B2B service temporarily unavailable"},
    },
)
async def get_facets(
    category: Optional[str] = Query(
        None,
        description="Filter by category UUID",
    ),
    min_price: Optional[float] = Query(
        None,
        ge=0,
        description="Minimum price filter",
    ),
    max_price: Optional[float] = Query(
        None,
        ge=0,
        description="Maximum price filter",
    ),
    in_stock: Optional[bool] = Query(
        None,
        description="Filter by stock availability",
    ),
    search: Optional[str] = Query(
        None,
        description="Search query for product name/description",
    ),
    session: AsyncSession = Depends(get_async_session),
) -> FacetResponse:
    """
    Get facet counts for the catalog.

    Returns aggregated counts for categories, price ranges, and stock availability
    based on products matching the given filters.
    """
    # Validate category UUID format
    if category:
        try:
            uuid.UUID(category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_CATEGORY",
                    "message": "category must be a valid UUID",
                },
            )

    # Validate price range
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PRICE_RANGE",
                "message": "min_price cannot be greater than max_price",
            },
        )

    query_params = ProductListQueryParams(
        offset=0,
        category=category,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        search=search,
    )

    service = CatalogService(session=session)

    try:
        result = await service.get_facets(query_params)
        return result
    except B2BServiceUnavailableError as e:
        logger.error(f"B2B service unavailable during facets fetch: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "B2B_UNAVAILABLE",
                "message": "Catalog service is temporarily unavailable",
            },
        )