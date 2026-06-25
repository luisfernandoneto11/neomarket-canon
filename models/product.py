"""
Product and SKU Models.

Represents the product and sku tables for B2B product management.
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Numeric,
    Integer,
    Boolean,
    CheckConstraint,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, UUID


class Product(Base):
    """
    Product model for storing B2B product information.
    
    This table stores product data with status tracking through the moderation lifecycle.
    """
    
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ON_MODERATION', 'MODERATED', 'BLOCKED', 'HARD_BLOCKED')",
            name="ck_product_status"
        ),
    )
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Product identifier"
    )
    
    # Seller reference
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        comment="Seller identifier"
    )
    
    # Product information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Product name"
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        String(2000),
        nullable=True,
        comment="Product description"
    )
    
    # Moderation fields
    blocking_reason: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Blocking reason with title and description"
    )
    
    field_reports: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        default=[],
        comment="List of field reports with validation issues"
    )
    
    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="DRAFT",
        comment="DRAFT, ON_MODERATION, MODERATED, BLOCKED, HARD_BLOCKED"
    )
    
    # Soft delete and catalog fields
    deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Soft delete flag"
    )
    
    active_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total active stock quantity across all SKUs"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Creation timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    
    # Relationships
    skus: Mapped[List["SKU"]] = relationship(
        "SKU",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="select"
    )
    
    def __repr__(self) -> str:
        return (
            f"<Product(id={self.id}, name={self.name}, status={self.status})>"
        )
    
    @property
    def is_draft(self) -> bool:
        """Check if product is in DRAFT status."""
        return self.status == "DRAFT"
    
    @property
    def is_on_moderation(self) -> bool:
        """Check if product is in ON_MODERATION status."""
        return self.status == "ON_MODERATION"
    
    @property
    def is_moderated(self) -> bool:
        """Check if product is in MODERATED status."""
        return self.status == "MODERATED"
    
    @property
    def is_blocked(self) -> bool:
        """Check if product is in BLOCKED status."""
        return self.status == "BLOCKED"
    
    @property
    def is_hard_blocked(self) -> bool:
        """Check if product is in HARD_BLOCKED status."""
        return self.status == "HARD_BLOCKED"


class SKU(Base):
    """
    SKU (Stock Keeping Unit) model for product variants.
    
    This table stores SKU information including pricing, inventory, and images.
    
    Invariant: active_quantity + reserved_quantity = on_hand
    """
    
    __tablename__ = "skus"
    __table_args__ = (
        UniqueConstraint("sku_code", name="uq_sku_code"),
        CheckConstraint(
            "price > 0",
            name="ck_sku_price_positive"
        ),
        CheckConstraint(
            "on_hand >= 0",
            name="ck_sku_on_hand_non_negative"
        ),
        CheckConstraint(
            "active_quantity >= 0",
            name="ck_sku_active_non_negative"
        ),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_sku_reserved_non_negative"
        ),
        CheckConstraint(
            "active_quantity + reserved_quantity = on_hand",
            name="ck_sku_stock_invariant"
        ),
    )
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="SKU identifier"
    )
    
    # Foreign key to product
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to parent product"
    )
    
    # SKU information
    sku_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unique SKU code (uppercase, min 3 chars)"
    )
    
    price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="SKU price (must be > 0)"
    )
    
    image_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="URL to SKU image"
    )
    
    on_hand: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total physical stock on hand (must be >= 0)"
    )
    
    active_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Active (available for sale) stock quantity"
    )
    
    reserved_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Reserved (allocated to orders) stock quantity"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Creation timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    
    # Relationships
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="skus",
        lazy="select"
    )
    
    def __repr__(self) -> str:
        return (
            f"<SKU(id={self.id}, sku_code={self.sku_code}, "
            f"price={self.price}, on_hand={self.on_hand}, "
            f"active={self.active_quantity}, reserved={self.reserved_quantity})>"
        )
    
    def verify_invariant(self) -> bool:
        """Verify that active + reserved = on_hand invariant holds."""
        return self.active_quantity + self.reserved_quantity == self.on_hand
    
    def reserve(self, quantity: int) -> bool:
        """
        Reserve stock if available.
        
        Returns True if reservation is successful, False otherwise.
        """
        if quantity > self.active_quantity:
            return False
        self.active_quantity -= quantity
        self.reserved_quantity += quantity
        return True
    
    def unreserve(self, quantity: int) -> bool:
        """
        Unreserve stock (release from reservation).
        
        Returns True if unreservation is successful, False otherwise.
        """
        if quantity > self.reserved_quantity:
            return False
        self.reserved_quantity -= quantity
        self.active_quantity += quantity
        return True
    
    def restore(self, quantity: int) -> None:
        """Restore stock (e.g., after unreserve, return to active)."""
        self.active_quantity += quantity
        self.on_hand += quantity
