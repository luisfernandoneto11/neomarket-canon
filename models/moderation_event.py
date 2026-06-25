"""
Moderation Event Model.

Represents the moderation_events table for idempotency tracking
of moderation decisions received from B2B.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, UUID


class ModerationEvent(Base):
    """
    Tracks processed moderation events for idempotency.
    
    When a moderation decision is received from B2B, we record
    the idempotency_key to prevent duplicate processing.
    """
    
    __tablename__ = "moderation_events"
    
    # Primary key - idempotency key from B2B
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        comment="Idempotency key (UUID) - prevents duplicate processing"
    )
    
    # Product reference
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Product UUID associated with this moderation event"
    )
    
    # Processing timestamp
    processed_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when the event was processed"
    )
    
    # Result stored as JSON
    result: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Moderation result data (status, blocking_reason, field_reports)"
    )
    
    def __repr__(self) -> str:
        return (
            f"<ModerationEvent(idempotency_key={self.idempotency_key}, "
            f"product_id={self.product_id})>"
        )