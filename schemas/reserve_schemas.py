"""
Pydantic schemas for stock reservation operations.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class ReserveItem(BaseModel):
    """Schema for a single item in a reservation request."""
    sku_id: str = Field(..., description="Unique identifier for the SKU")
    quantity: int = Field(..., gt=0, description="Quantity to reserve")


class ReserveRequest(BaseModel):
    """Schema for a stock reservation request."""
    idempotency_key: str = Field(..., description="Unique key to ensure idempotent requests")
    items: List[ReserveItem] = Field(..., min_length=1, description="List of items to reserve")


class ReserveItemResponse(BaseModel):
    """Schema for a single item in a reservation response."""
    sku_id: str = Field(..., description="Unique identifier for the SKU")
    reserved_quantity: int = Field(..., ge=0, description="Quantity successfully reserved")
    remaining_stock: int = Field(..., ge=0, description="Remaining stock after reservation")


class ReserveResponse(BaseModel):
    """Schema for a successful stock reservation response."""
    reserved: bool = Field(True, description="Whether the reservation was successful")
    items: List[ReserveItemResponse] = Field(..., description="List of reserved items with details")


class FailedItem(BaseModel):
    """Schema for a single failed item in a reservation."""
    sku_id: str = Field(..., description="Unique identifier for the SKU")
    reason: str = Field(..., description="Reason why the reservation failed")


class ReserveErrorResponse(BaseModel):
    """Schema for a failed stock reservation response."""
    reserved: bool = Field(False, description="Whether the reservation was successful")
    failed_items: List[FailedItem] = Field(..., description="List of items that failed to reserve")


class UnreserveItem(BaseModel):
    """Schema for a single item in an unreserve request."""
    sku_id: str = Field(..., description="Unique identifier for the SKU")
    quantity: int = Field(..., gt=0, description="Quantity to unreserve")


class UnreserveRequest(BaseModel):
    """Schema for a stock unreservation request."""
    order_id: str = Field(..., description="Unique identifier for the order")
    items: List[UnreserveItem] = Field(..., min_length=1, description="List of items to unreserve")


class UnreserveResponse(BaseModel):
    """Schema for a successful stock unreservation response."""
    ok: bool = Field(True, description="Whether the unreservation was successful")