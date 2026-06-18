"""
Product Moderation Model.

Represents the product_moderation table which stores moderation cards for products
coming from B2B for review by moderators.
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class ProductModeration(Base):
    """
    Product moderation record for tracking product lifecycle through moderation process.
    
    This table stores snapshots of product data (json_before, json_after) and tracks
    the moderation status through the workflow: PENDING -> IN_REVIEW -> MODERATED/BLOCKED/HARD_BLOCKED
    """
    
    __tablename__ = "product_moderation"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_product_moderation_product_id"),
        CheckConstraint(
            "status IN ('PENDING', 'IN_REVIEW', 'MODERATED', 'BLOCKED', 'HARD_BLOCKED')",
            name="ck_product_moderation_status"
        ),
        CheckConstraint(
            "queue_priority >= 1 AND queue_priority <= 4",
            name="ck_product_moderation_queue_priority"
        ),
        {"schema": None},  # Use default schema
    )
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Идентификатор записи"
    )
    
    # Product and seller references
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="ID товара в B2B (one-to-one)"
    )
    
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="ID продавца (из события B2B)"
    )
    
    # Moderation status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        comment="PENDING, IN_REVIEW, MODERATED, BLOCKED, HARD_BLOCKED"
    )
    
    # Queue priority (1-4)
    queue_priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Номер очереди: 1-4 (вычисляется при обработке события)"
    )
    
    # Product data snapshots
    json_before: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Состояние товара ДО изменений (null для новых)"
    )
    
    json_after: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Текущее состояние товара (GET /api/v1/products/{id} из B2B)"
    )
    
    # Blocking information
    blocking_reason_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_blocking_reasons.id", ondelete="SET NULL"),
        nullable=True,
        comment="Причина блокировки"
    )
    
    # Moderator information
    moderator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID модератора, взявшего карточку (get-next) или принявшего решение"
    )
    
    moderator_comment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Общий комментарий при блокировке"
    )
    
    # Timestamps
    date_created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Дата создания записи"
    )
    
    date_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Дата последнего обновления (при каждом событии от B2B)"
    )
    
    date_moderation: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата последнего решения модератора"
    )
    
    # Relationships
    blocking_reason: Mapped[Optional["ProductBlockingReason"]] = relationship(
        "ProductBlockingReason",
        back_populates="moderation_records",
        lazy="select"
    )
    
    field_reports: Mapped[List["ProductModerationFieldReport"]] = relationship(
        "ProductModerationFieldReport",
        back_populates="product_moderation",
        cascade="all, delete-orphan",
        lazy="select"
    )
    
    def __repr__(self) -> str:
        return (
            f"<ProductModeration(id={self.id}, product_id={self.product_id}, "
            f"status={self.status}, queue_priority={self.queue_priority})>"
        )
    
    @property
    def is_pending(self) -> bool:
        """Check if moderation card is in PENDING status."""
        return self.status == "PENDING"
    
    @property
    def is_in_review(self) -> bool:
        """Check if moderation card is in IN_REVIEW status."""
        return self.status == "IN_REVIEW"
    
    @property
    def is_moderated(self) -> bool:
        """Check if moderation card is in MODERATED status."""
        return self.status == "MODERATED"
    
    @property
    def is_blocked(self) -> bool:
        """Check if moderation card is in BLOCKED status."""
        return self.status == "BLOCKED"
    
    @property
    def is_hard_blocked(self) -> bool:
        """Check if moderation card is in HARD_BLOCKED status."""
        return self.status == "HARD_BLOCKED"
    
    @property
    def is_terminal(self) -> bool:
        """Check if moderation card is in terminal status (HARD_BLOCKED)."""
        return self.status == "HARD_BLOCKED"
    
    def can_be_edited(self) -> bool:
        """Check if product can be edited (not HARD_BLOCKED)."""
        return self.status != "HARD_BLOCKED"
    
    def can_be_reviewed(self) -> bool:
        """Check if moderation card can be taken for review."""
        return self.status == "PENDING"
    
    def can_be_decided(self) -> bool:
        """Check if decision can be made on this moderation card."""
        return self.status == "IN_REVIEW"