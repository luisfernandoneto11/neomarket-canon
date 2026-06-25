"""
Order and OrderItem Models.

Represents the orders and order_items tables for B2C order management.
Supports idempotency via unique constraint on idempotency_key.
Prices and titles are fixed at order creation time (price snapshot).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, UUID


class OrderStatus(str, SAEnum):
    """Order status lifecycle."""
    CREATED = "CREATED"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    CANCEL_PENDING = "CANCEL_PENDING"


class Order(Base):
    """
    Order model for B2C orders.

    Identity is user_id for authenticated users.
    Idempotency is guaranteed via unique constraint on idempotency_key.
    """

    __tablename__ = "orders"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Order status
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=OrderStatus.CREATED,
    )

    # Total amount in cents
    total_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Idempotency key - UNIQUE constraint prevents duplicate orders
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Cancel pending tracking
    cancel_pending_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        description="Timestamp when order entered CANCEL_PENDING state",
    )

    # Relationships
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, user_id={self.user_id}, "
            f"status={self.status}, total_amount={self.total_amount})>"
        )


class OrderItem(Base):
    """
    OrderItem model for individual items in an order.

    Prices and titles are fixed at order creation time (price snapshot).
    sku_id is kept for reference/tracking purposes.
    """

    __tablename__ = "order_items"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign key to order
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SKU reference (for tracking)
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # Price snapshot - fixed at order creation time
    product_title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    sku_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    unit_price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    total_price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
        lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<OrderItem(id={self.id}, order_id={self.order_id}, "
            f"sku_id={self.sku_id}, quantity={self.quantity})>"
        )