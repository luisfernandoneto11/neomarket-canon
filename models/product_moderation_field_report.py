"""
Product Moderation Field Report Model.

Represents the product_moderation_field_report table which stores specific field-level
issues identified by moderators during product review.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Text,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, UUID


class ProductModerationFieldReport(Base):
    """
    Field-level report for moderation issues.
    
    Stores specific issues identified by moderators for individual product fields
    (title, description, images, category, SKU details, etc.).
    """
    
    __tablename__ = "product_moderation_field_report"
    __table_args__ = (
        CheckConstraint(
            "field_name IN ('title', 'description', 'product_images', 'category', 'sku_name', 'sku_image', 'sku_price')",
            name="ck_field_report_field_name"
        ),
        {"schema": None},  # Use default schema
    )
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Идентификатор"
    )
    
    # Reference to moderation record
    product_moderation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_moderation.id", ondelete="CASCADE"),
        nullable=False,
        comment="Ссылка на запись модерации"
    )
    
    # Field information
    field_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Допустимые значения: title, description, product_images, category, sku_name, sku_image, sku_price"
    )
    
    # Optional SKU reference (null = issue with product, not SKU)
    sku_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID конкретного SKU (null = замечание к товару, не к SKU)"
    )
    
    # Comment about the issue
    comment: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Комментарий модератора"
    )
    
    # Timestamp
    date_created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Дата создания"
    )
    
    # Relationships
    product_moderation: Mapped["ProductModeration"] = relationship(
        "ProductModeration",
        back_populates="field_reports"
    )
    
    def __repr__(self) -> str:
        return (
            f"<ProductModerationFieldReport(id={self.id}, "
            f"product_moderation_id={self.product_moderation_id}, "
            f"field_name={self.field_name})>"
        )
    
    @property
    def is_product_level_issue(self) -> bool:
        """Check if this is a product-level issue (not SKU-specific)."""
        return self.sku_id is None
    
    @property
    def is_sku_level_issue(self) -> bool:
        """Check if this is a SKU-specific issue."""
        return self.sku_id is not None