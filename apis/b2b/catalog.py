"""
B2B Catalog API Router for public product catalog.

Provides endpoints for browsing the product catalog with pagination.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from schemas.catalog_schemas import CatalogResponse
from services.catalog_service import CatalogService


router = APIRouter(
    prefix="/api/v1",
    tags=["B2B - Catalog"],
)


@router.get(
    "/products",
    response_model=CatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="List products in catalog",
    description="Retrieve a paginated list of active products available in the catalog.",
    responses={
        200: {"description": "Catalog retrieved successfully"},
    },
)
async def list_catalog_products(
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
    session: AsyncSession = Depends(get_async_session),
) -> CatalogResponse:
    """
    List products in the public catalog.
    
    Returns a paginated list of active, moderated products that are not deleted.
    Only products with status 'MODERATED' and deleted=False are included.
    
    Args:
        limit: Maximum number of items per page (default 20, max 100).
        offset: Number of items to skip for pagination.
        session: Database session.
        
    Returns:
        CatalogResponse with paginated product list and metadata.
    """
    service = CatalogService(session)
    return await service.get_catalog(limit=limit, offset=offset)