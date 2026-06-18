"""
Base SQLAlchemy model for NeoMarket Moderation Service.

This module contains the base declarative class for all database models.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models in the Moderation service.
    
    This class provides the foundation for all database models and includes
    common functionality that can be shared across models.
    """
    pass