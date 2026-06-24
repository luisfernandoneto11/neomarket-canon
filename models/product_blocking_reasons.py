"""
Product Blocking Reasons Model.

Represents the product_blocking_reasons table which stores predefined reasons
for blocking products during moderation. Includes seed data for initial setup.
"""

import uuid
from typing import List

from sqlalchemy import Column, String, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .base import Base, UUID


class ProductBlockingReason(Base):
    """
    Reference table for product blocking reasons.
    
    Contains predefined reasons that moderators can select when blocking a product.
    Each reason has a hard_block flag indicating if it's a permanent block.
    """
    
    __tablename__ = "product_blocking_reasons"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Идентификатор"
    )
    
    # Reason details
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Текст причины блокировки"
    )
    
    hard_block: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="true = перманентная блокировка"
    )
    
    # Relationships
    moderation_records: Mapped[List["ProductModeration"]] = relationship(
        "ProductModeration",
        back_populates="blocking_reason"
    )
    
    def __repr__(self) -> str:
        return (
            f"<ProductBlockingReason(id={self.id}, title='{self.title}', "
            f"hard_block={self.hard_block})>"
        )
    
    @property
    def is_hard_block(self) -> bool:
        """Check if this reason results in a hard block."""
        return self.hard_block


# Seed data for initial blocking reasons
SEED_BLOCKING_REASONS = [
    {
        "id": "a7b8c9d0-1234-5678-ef01-890123456789",
        "title": "Описание не соответствует товару",
        "hard_block": False,
    },
    {
        "id": "b8c9d0e1-2345-6789-f012-901234567890",
        "title": "Изображение не соответствует товару",
        "hard_block": False,
    },
    {
        "id": "c9d0e1f2-3456-7890-0123-012345678901",
        "title": "Некорректная категория товара",
        "hard_block": False,
    },
    {
        "id": "d0e1f2a3-4567-8901-1234-123456789012",
        "title": "Недостаточно информации о товаре",
        "hard_block": False,
    },
    {
        "id": "e1f2a3b4-5678-9012-2345-234567890123",
        "title": "Нецензурные или оскорбительные материалы",
        "hard_block": False,
    },
    {
        "id": "f2a3b4c5-6789-0123-3456-345678901234",
        "title": "Дублирование существующего товара",
        "hard_block": False,
    },
    {
        "id": "a3b4c5d6-7890-1234-4567-456789012345",
        "title": "Некорректная цена",
        "hard_block": False,
    },
    {
        "id": "b4c5d6e7-8901-2345-5678-567890123456",
        "title": "Контрафактный товар",
        "hard_block": True,
    },
    {
        "id": "c5d6e7f8-9012-3456-6789-678901234567",
        "title": "Товар запрещён к продаже на территории РФ",
        "hard_block": True,
    },
    {
        "id": "d6e7f8a9-0123-4567-7890-789012345678",
        "title": "Товар нарушает авторские права",
        "hard_block": True,
    },
]


def get_seed_blocking_reasons() -> List[ProductBlockingReason]:
    """
    Get seed data for blocking reasons.
    
    Returns:
        List of ProductBlockingReason instances with predefined data.
    """
    return [
        ProductBlockingReason(
            id=uuid.UUID(reason["id"]),
            title=reason["title"],
            hard_block=reason["hard_block"],
        )
        for reason in SEED_BLOCKING_REASONS
    ]