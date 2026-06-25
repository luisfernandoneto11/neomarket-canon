"""
Product Card Pydantic Schemas for B2C product detail endpoint.

Used in the product card endpoint to return product and SKU data
to end consumers viewing a product detail page.
IMPORTANT: These schemas never expose cost_price or reserved_quantity.
"""

import uuid
from typing import Optional, List

from pydantic import BaseModel, Field


class ProductImageResponse(BaseModel):
    """Schema for product image data."""

    url: str = Field(
        ...,
        description="Image URL"
    )
    ordering: int = Field(
        ...,
        description="Image ordering position (0 = first)"
    )

    class Config:
        from_attributes = True


class CharacteristicResponse(BaseModel):
    """Schema for product/SKU characteristic."""

    name: str = Field(
        ...,
        description="Characteristic name"
    )
    value: str = Field(
        ...,
        description="Characteristic value"
    )

    class Config:
        from_attributes = True


class SKUCardResponse(BaseModel):
    """
    Schema for SKU data in B2C product card.
    
    IMPORTANT: Does NOT include cost_price or reserved_quantity.
    These are seller-sensitive fields excluded from B2C responses.
    """

    id: uuid.UUID = Field(
        ...,
        description="SKU identifier"
    )
    name: str = Field(
        ...,
        description="SKU name/variant (e.g. '256GB Black')"
    )
    price: int = Field(
        ...,
        description="SKU price in cents"
    )
    discount: int = Field(
        default=0,
        description="Discount amount in cents (0 = no discount)"
    )
    image: Optional[str] = Field(
        None,
        description="SKU image URL"
    )
    in_stock: bool = Field(
        ...,
        description="Whether this SKU is currently in stock"
    )
    active_quantity: int = Field(
        ...,
        description="Available quantity for this SKU"
    )
    characteristics: List[CharacteristicResponse] = Field(
        default_factory=list,
        description="SKU-specific characteristics (color, size, etc.)"
    )

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    """Schema for product category."""

    id: uuid.UUID = Field(
        ...,
        description="Category identifier"
    )
    name: str = Field(
        ...,
        description="Category name"
    )

    class Config:
        from_attributes = True


class ProductCardResponse(BaseModel):
    """
    Schema for B2C product card response.
    
    Returned by GET /api/v1/products/{id}.
    Contains full product detail with images, characteristics, and SKU list.
    Only visible products (status=MODERATED, deleted=false) are returned.
    """

    id: uuid.UUID = Field(
        ...,
        description="Product identifier"
    )
    slug: Optional[str] = Field(
        None,
        description="Product URL slug"
    )
    title: str = Field(
        ...,
        description="Product title"
    )
    description: Optional[str] = Field(
        None,
        description="Product description"
    )
    status: str = Field(
        ...,
        description="Product status (MODERATED for visible products)"
    )
    category: Optional[CategoryResponse] = Field(
        None,
        description="Product category"
    )
    images: List[ProductImageResponse] = Field(
        default_factory=list,
        description="Product images ordered by ordering field"
    )
    characteristics: List[CharacteristicResponse] = Field(
        default_factory=list,
        description="Product-level characteristics (brand, country, etc.)"
    )
    skus: List[SKUCardResponse] = Field(
        default_factory=list,
        description="List of SKU variants for this product"
    )

    class Config:
        from_attributes = True