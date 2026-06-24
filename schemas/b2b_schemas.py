"""
B2B Pydantic Schemas for product and SKU management.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator, HttpUrl


class SKUCreateRequest(BaseModel):
    """
    Schema for creating a new SKU.
    
    Validates the request body for POST /api/v1/skus endpoint.
    """
    
    product_id: uuid.UUID = Field(
        ...,
        description="UUID of the parent product",
        examples=["123e4567-e89b-12d3-a456-426614174000"]
    )
    
    sku_code: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique SKU code (will be converted to uppercase)",
        examples=["SKU001"]
    )
    
    price: float = Field(
        ...,
        gt=0,
        description="SKU price (must be greater than 0)",
        examples=[99.99]
    )
    
    image_url: Optional[HttpUrl] = Field(
        None,
        description="URL to SKU image (must be valid URL)",
        examples=["https://example.com/product.jpg"]
    )
    
    stock_quantity: int = Field(
        default=0,
        ge=0,
        description="Available stock quantity (must be >= 0)",
        examples=[10]
    )
    
    @field_validator("sku_code")
    @classmethod
    def validate_sku_code(cls, v: str) -> str:
        """
        Validate and normalize SKU code.
        
        - Converts to uppercase
        - Ensures minimum length of 3 characters
        """
        v = v.upper().strip()
        if len(v) < 3:
            raise ValueError("sku_code must have at least 3 characters")
        return v
    
    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float) -> float:
        """
        Validate price is positive.
        """
        if v <= 0:
            raise ValueError("price must be greater than 0")
        return round(v, 2)
    
    @field_validator("stock_quantity")
    @classmethod
    def validate_stock_quantity(cls, v: int) -> int:
        """
        Validate stock quantity is non-negative.
        """
        if v < 0:
            raise ValueError("stock_quantity must be >= 0")
        return v


class SKUResponse(BaseModel):
    """
    Schema for SKU response.
    
    Used in API responses to return SKU data.
    """
    
    id: uuid.UUID = Field(
        ...,
        description="SKU identifier"
    )
    
    product_id: uuid.UUID = Field(
        ...,
        description="Reference to parent product"
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
    
    created_at: datetime = Field(
        ...,
        description="Creation timestamp"
    )
    
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp"
    )
    
    class Config:
        from_attributes = True


class ProductResponse(BaseModel):
    """
    Schema for Product response.
    
    Used in API responses to return product data with SKUs.
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
        description="Product status: DRAFT, ON_MODERATION, MODERATED, BLOCKED, HARD_BLOCKED"
    )
    
    skus: List[SKUResponse] = Field(
        default_factory=list,
        description="List of SKUs for this product"
    )
    
    created_at: datetime = Field(
        ...,
        description="Creation timestamp"
    )
    
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp"
    )
    
    class Config:
        from_attributes = True


class EventPayload(BaseModel):
    """
    Schema for event payload.
    
    Contains the data snapshot for an event.
    """
    
    json_after: Dict[str, Any] = Field(
        ...,
        description="Data after the event occurred"
    )


class ModerationEvent(BaseModel):
    """
    Schema for moderation events.
    
    Used for event-driven architecture with idempotency support.
    """
    
    event_type: str = Field(
        ...,
        description="Type of event (e.g., SKU_CREATED, SKU_UPDATED)"
    )
    
    idempotency_key: uuid.UUID = Field(
        ...,
        description="Unique key for event deduplication"
    )
    
    occurred_at: datetime = Field(
        ...,
        description="Timestamp when the event occurred"
    )
    
    payload: EventPayload = Field(
        ...,
        description="Event data payload"
    )