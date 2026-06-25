"""
B2B Products API router for product management.

Provides endpoints for creating, retrieving, and managing products.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import uuid

from models.database import get_async_session
from models.product import Product
from services.b2b_service import B2BService, ProductNotFoundError


router = APIRouter(
    prefix="/api/v1",
    tags=["B2B - Products"],
)


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new product",
    description="Create a new product in DRAFT status.",
    responses={
        201: {"description": "Product created successfully"},
        422: {"description": "Schema validation failed"},
    },
)
async def create_product(
    name: str,
    description: str = None,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new product.
    
    This endpoint creates a new product in DRAFT status.
    
    Args:
        name: Product name
        description: Product description
        session: Database session
        
    Returns:
        Product data
    """
    service = B2BService(session)
    
    new_product = Product(
        name=name,
        description=description,
        status="DRAFT",
    )
    
    session.add(new_product)
    await session.commit()
    await session.refresh(new_product)
    
    return {
        "id": str(new_product.id),
        "name": new_product.name,
        "description": new_product.description,
        "status": new_product.status,
        "created_at": new_product.created_at.isoformat(),
        "updated_at": new_product.updated_at.isoformat(),
    }


@router.get(
    "/products/{product_id}",
    summary="Get a product by ID",
    description="Retrieve product details including SKUs, blocking reason, and field reports.",
    responses={
        200: {"description": "Product found"},
        404: {"description": "Product not found"},
    },
)
async def get_product(
    product_id: uuid.UUID,
    seller_id: uuid.UUID = None,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get a product by ID.
    
    Args:
        product_id: Product UUID
        seller_id: Optional seller ID for authorization check
        session: Database session
        
    Returns:
        Product data with SKUs, blocking reason, and field reports
        
    Raises:
        HTTPException 404: If product not found or doesn't belong to seller
    """
    # Eagerly load skus to avoid lazy loading outside async context
    query = (
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.skus))
    )
    result = await session.execute(query)
    product = result.scalars().unique().first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )
    
    # Check if product belongs to the seller
    if seller_id and product.seller_id != seller_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {product_id} not found"
        )
    
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "status": product.status,
        "blocking_reason": product.blocking_reason,
        "field_reports": product.field_reports or [],
        "skus": [
            {
                "id": str(sku.id),
                "sku_code": sku.sku_code,
                "price": float(sku.price),
                "image_url": sku.image_url,
                "stock_quantity": sku.stock_quantity,
                "created_at": sku.created_at.isoformat(),
                "updated_at": sku.updated_at.isoformat(),
            }
            for sku in product.skus
        ],
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }
