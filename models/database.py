"""
Database configuration and session management for NeoMarket Moderation Service.

This module provides database connection setup, session management,
and utility functions for working with the database.
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from .base import Base
from .product_moderation import ProductModeration
from .product_moderation_field_report import ProductModerationFieldReport
from .product_blocking_reasons import ProductBlockingReason, get_seed_blocking_reasons

# Database URL - should be configured via environment variable
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/neomarket_moderation")

# Create async engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
    )
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.
    
    Yields:
        AsyncSession: Database session for async operations.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.
    
    Creates all tables defined in the models.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_blocking_reasons(session: AsyncSession) -> None:
    """
    Seed the blocking reasons table with initial data.
    
    Args:
        session: Database session to use for seeding.
    """
    # Check if data already exists
    from sqlalchemy import select
    result = await session.execute(select(ProductBlockingReason))
    existing = result.scalars().first()
    
    if existing is None:
        # No data exists, seed it
        seed_data = get_seed_blocking_reasons()
        for reason in seed_data:
            # Double check by ID to prevent IntegrityError
            res = await session.execute(select(ProductBlockingReason).where(ProductBlockingReason.id == reason.id))
            if res.scalars().first() is None:
                session.add(reason)
        await session.commit()


async def close_db() -> None:
    """
    Close database connections.
    
    Should be called during application shutdown.
    """
    await engine.dispose()