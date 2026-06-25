"""
Base SQLAlchemy model for NeoMarket Moderation Service.

This module contains the base declarative class for all database models.
"""

import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class UUID(TypeDecorator):
    """
    Database-agnostic UUID type.
    
    Uses PostgreSQL's native UUID type when available,
    falls back to String(36) for SQLite and other databases.
    """
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models in the Moderation service.
    
    This class provides the foundation for all database models and includes
    common functionality that can be shared across models.
    """
    pass
