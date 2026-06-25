"""
Order schemas for B2C Order service.

Defines request/response models for order creation from cart,
including idempotency support and price snapshot at purchase time.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """Order status lifecycle."""
    PENDING = "PENDING"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CheckoutItem(BaseModel):
    """Individual item in a checkout request."""
    sku_id: str = Field(..., description="SKU UUID to purchase")
    quantity: int = Field(..., ge=1, description="Quantity to purchase (minimum 1)")


class CheckoutRequest(BaseModel):
    """
    Request to create an order from cart.
    
    Uses idempotency_key to prevent duplicate orders.
    """
    idempotency_key: str = Field(
        ...,
        description="UUID for idempotent order creation (prevents duplicates)"
    )
    items: list[CheckoutItem] = Field(
        ...,
        min_length=1,
        description="List of items to purchase"
    )


class OrderItemResponse(BaseModel):
    """
    Response for a single order item.
    
    Prices and titles are fixed at the time of order creation (price snapshot).
    """
    id: str = Field(..., description="Order item UUID")
    sku_id: str = Field(..., description="SKU UUID")
    product_title: str = Field(
        ...,
        description="Product title (fixed at purchase time)"
    )
    sku_name: str = Field(
        ...,
        description="SKU name/variant (fixed at purchase time)"
    )
    unit_price: int = Field(
        ...,
        description="Unit price in cents (fixed at purchase time)"
    )
    quantity: int = Field(..., description="Quantity purchased")
    total_price: int = Field(
        ...,
        description="Total price for this item (unit_price * quantity)"
    )


class OrderResponse(BaseModel):
    """
    Response for a created order.
    
    Contains all order details including the idempotency key
    for future reference.
    """
    id: str = Field(..., description="Order UUID")
    user_id: str = Field(..., description="User UUID who placed the order")
    status: OrderStatus = Field(..., description="Current order status")
    total_amount: int = Field(
        ...,
        description="Total order amount in cents"
    )
    items: list[OrderItemResponse] = Field(
        ...,
        description="List of order items"
    )
    created_at: datetime = Field(
        ...,
        description="Order creation timestamp"
    )
    idempotency_key: str = Field(
        ...,
        description="Idempotency key used for this order"
    )