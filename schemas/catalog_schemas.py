"""
Catalog Pydantic Schemas for catalog-related responses.

Used in public catalog endpoints to return product and SKU data
to end consumers browsing the marketplace.
"""

import uuid
from typing import Optional, List

from pydantic import BaseModel, Field


class SKUCatalogResponse(BaseModel):
    """
    Schema for SKU information in catalog responses.

    Used to return SKU data in the public catalog context.
    Contains pricing, imagery, and stock availability information.
    """

    id: uuid.UUID = Field(
        ...,
        description="SKU identifier"
    )

    sku_code: str = Field(
        ...,
        description="Unique SKU code"
    )

    price: float = Field(
        ...,
        description="SKU price"
    )

    image_url: Optional[str] = Field(
        None,
        description="URL to SKU image"
    )

    stock_quantity: int = Field(
        ...,
        description="Available stock quantity"
    )

    class Config:
        from_attributes = True


class ProductCatalogResponse(BaseModel):
    """
    Schema for product information in catalog responses.

    Used to return product data in the public catalog context.
    Contains product metadata and associated SKUs.
    """

    id: uuid.UUID = Field(
        ...,
        description="Product identifier"
    )

    name: str = Field(
        ...,
        description="Product name"
    )

    description: Optional[str] = Field(
        None,
        description="Product description"
    )

    status: str = Field(
        ...,
        description="Product status: ACTIVE, INACTIVE, etc."
    )

    skus: List[SKUCatalogResponse] = Field(
        default_factory=list,
        description="List of SKUs for this product"
    )

    class Config:
        from_attributes = True


class CatalogResponse(BaseModel):
    """
    Schema for paginated catalog response.

    Used as the top-level response for catalog list endpoints,
    containing pagination metadata and product items.
    """

    items: List[ProductCatalogResponse] = Field(
        ...,
        description="List of products in the catalog"
    )

    total: int = Field(
        ...,
        description="Total number of products matching the query"
    )

    limit: int = Field(
        ...,
        description="Maximum number of items per page"
    )

    offset: int = Field(
        ...,
        description="Number of items skipped (for pagination)"
    )

    class Config:
        from_attributes = True