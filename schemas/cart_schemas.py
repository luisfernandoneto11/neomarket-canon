"""
Cart schemas for B2C Cart service.

Defines request/response models for cart operations including
availability enrichment from B2B.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class UnavailableReason(str, Enum):
    """Reasons why a cart item may be unavailable."""
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    PRODUCT_DELETED = "PRODUCT_DELETED"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"


class CartItemAddRequest(BaseModel):
    """Request to add an item to the cart."""
    sku_id: str = Field(..., description="SKU UUID to add")
    quantity: int = Field(..., ge=1, description="Quantity to add (minimum 1)")


class CartItemUpdateRequest(BaseModel):
    """Request to update the quantity of a cart item."""
    quantity: int = Field(..., ge=0, description="New quantity (0 removes the item)")


class CartItemResponse(BaseModel):
    """Response for a single cart item with enriched data from B2B."""
    sku_id: str = Field(..., description="SKU UUID")
    sku_data: Optional[dict] = Field(
        None,
        description="Enriched SKU data from B2B (title, price, images, etc.)"
    )
    quantity: int = Field(..., description="Quantity in cart")
    unavailable_reason: Optional[UnavailableReason] = Field(
        None,
        description="Reason if item is unavailable (null if available)"
    )


class CartResponse(BaseModel):
    """Response for the full cart."""
    items: list[CartItemResponse] = Field(default=[], description="Cart items")
    total_amount: int = Field(default=0, description="Total cart amount in cents")
    total_items: int = Field(default=0, description="Total number of items")