"""
Cart and CartItem Models.

Represents the cart_items table for B2C cart management.
Supports both authenticated users (user_id) and guests (session_id).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Integer,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, UUID


class Cart(Base):
    """
    Cart model for B2C shopping cart.

    Identity is either user_id (authenticated) or session_id (guest).
    At least one must be set.
    """

    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR session_id IS NOT NULL",
            name="ck_cart_identity"
        ),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identity: user_id for authenticated, session_id for guest
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    session_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
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

    # Relationships
    items: Mapped[list["CartItem"]] = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<Cart(id={self.id}, user_id={self.user_id}, "
            f"session_id={self.session_id})>"
        )


class CartItem(Base):
    """
    CartItem model for individual items in a cart.

    Each row represents a SKU + quantity pair belonging to a cart.
    Uniqueness guaranteed per (cart_id, sku_id).
    """

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "sku_id", name="uq_cart_item_sku"),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign key to cart
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Item data
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Timestamps
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    cart: Mapped["Cart"] = relationship(
        "Cart",
        back_populates="items",
        lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<CartItem(id={self.id}, cart_id={self.cart_id}, "
            f"sku_id={self.sku_id}, quantity={self.quantity})>"
        )
