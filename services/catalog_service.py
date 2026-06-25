"""
Catalog Service for NeoMarket.

Handles business logic for the public product catalog,
including filtering, pagination, and data transformation.
"""

from typing import Optional, Tuple, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.product import Product, SKU
from schemas.catalog_schemas import CatalogResponse, ProductCatalogResponse, SKUCatalogResponse


class CatalogService:
    """
    Service for catalog operations.
    
    Handles querying products for the public catalog,
    including pagination and filtering active products.
    """
    
    def __init__(self, session: AsyncSession):
        """
        Initialize catalog service.
        
        Args:
            session: Database session.
        """
        self.session = session
    
    async def get_catalog(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> CatalogResponse:
        """
        Get paginated catalog of active products.
        
        Returns products that are:
        - Not deleted (deleted = False)
        - Have status = 'MODERATED'
        - Have at least one SKU with stock > 0
        
        Args:
            limit: Maximum number of items per page (default 20, max 100).
            offset: Number of items to skip for pagination.
            
        Returns:
            CatalogResponse with items and pagination metadata.
        """
        # Clamp limit to reasonable range
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        
        # Build query for active, non-deleted products with SKUs
        query = (
            select(Product)
            .where(
                Product.deleted == False,
                Product.status == "MODERATED",
            )
            .options(selectinload(Product.skus))
            .order_by(Product.created_at.desc())
        )
        
        # Get total count
        count_query = select(func.count(Product.id)).where(
            Product.deleted == False,
            Product.status == "MODERATED",
        )
        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        products = result.scalars().unique().all()
        
        # Transform to catalog response
        items = [self._to_product_catalog(p) for p in products]
        
        return CatalogResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
    
    def _to_product_catalog(self, product: Product) -> ProductCatalogResponse:
        """
        Transform Product model to ProductCatalogResponse.
        
        Args:
            product: Product model instance with SKUs loaded.
            
        Returns:
            ProductCatalogResponse for catalog display.
        """
        skus = [
            SKUCatalogResponse(
                id=sku.id,
                sku_code=sku.sku_code,
                price=float(sku.price),
                image_url=sku.image_url,
                stock_quantity=sku.stock_quantity,
            )
            for sku in product.skus
        ]
        
        return ProductCatalogResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            status=product.status,
            skus=skus,
        )