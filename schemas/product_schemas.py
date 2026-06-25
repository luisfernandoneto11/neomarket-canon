"""
Product Pydantic Schemas for moderation-related responses.
"""

import uuid
from typing import Optional, List, Any

from pydantic import BaseModel, Field


class BlockingReason(BaseModel):
    """
    Schema for blocking reason information.
    
    Used when a product is blocked during moderation to provide
    context about why the block occurred.
    """
    
    title: str = Field(
        ...,
        description="Short title describing the blocking reason",
        examples=["Incomplete Product Information"]
    )
    
    description: str = Field(
        ...,
        description="Detailed description of the blocking reason",
        examples=["Product description is missing or too short"]
    )


class FieldReport(BaseModel):
    """
    Schema for field-level validation reports.
    
    Contains information about specific field validation issues
    found during moderation.
    """
    
    field: str = Field(
        ...,
        description="Name of the field with the validation issue",
        examples=["name", "description", "price"]
    )
    
    message: str = Field(
        ...,
        description="Human-readable validation message",
        examples=["Field is required", "Value must be at least 3 characters"]
    )
    
    value: Optional[Any] = Field(
        None,
        description="The actual value that failed validation",
        examples=["", "AB", -5]
    )
    
    suggestion: Optional[str] = Field(
        None,
        description="Suggested fix for the validation issue",
        examples=["Provide a more descriptive name", "Use at least 3 characters"]
    )


class SKUDetailResponse(BaseModel):
    """
    Schema for detailed SKU response.
    
    Used in product detail responses to return complete SKU information
    including reserved quantity.
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
    
    cost_price: Optional[float] = Field(
        None,
        description="SKU cost price (if available)"
    )
    
    image_url: Optional[str] = Field(
        None,
        description="URL to SKU image"
    )
    
    stock_quantity: int = Field(
        ...,
        description="Available stock quantity"
    )
    
    reserved_quantity: int = Field(
        default=0,
        description="Reserved stock quantity"
    )
    
    class Config:
        from_attributes = True


class ProductDetailResponse(BaseModel):
    """
    Schema for detailed product response.
    
    Used in product detail endpoints to return complete product information
    including moderation data and SKU details.
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
    
    blocking_reason: Optional[BlockingReason] = Field(
        None,
        description="Blocking reason (only present when product is blocked)"
    )
    
    field_reports: List[FieldReport] = Field(
        default_factory=list,
        description="List of field validation reports"
    )
    
    skus: List[SKUDetailResponse] = Field(
        default_factory=list,
        description="List of SKUs for this product"
    )
    
    class Config:
        from_attributes = True