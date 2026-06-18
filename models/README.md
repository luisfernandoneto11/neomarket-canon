# Database Models for NeoMarket Moderation Service

This directory contains SQLAlchemy database models for the US-MOD-01 implementation: receiving product events from B2B for the Moderation service.

## Overview

The models implement the database schema required for the product moderation workflow, including:

- **Product moderation tracking** - Store and manage moderation cards for products
- **Field-level reporting** - Track specific issues with product fields
- **Blocking reasons** - Reference table for predefined blocking reasons

## Project Stack

- **Database**: PostgreSQL 14+
- **ORM**: SQLAlchemy 2.0+ (async)
- **Driver**: asyncpg
- **Python**: 3.11+

## Models

### 1. ProductModeration (`product_moderation.py`)

Main table for tracking product moderation lifecycle.

**Table**: `product_moderation`

**Key Fields**:
- `id` (UUID, PK) - Record identifier
- `product_id` (UUID, UNIQUE, NOT NULL) - Product ID from B2B (one-to-one)
- `seller_id` (UUID, NOT NULL) - Seller ID from B2B event
- `status` (VARCHAR) - Moderation status: PENDING, IN_REVIEW, MODERATED, BLOCKED, HARD_BLOCKED
- `queue_priority` (INTEGER 1-4) - Queue number for prioritization
- `json_before` (JSONB, nullable) - Product state BEFORE changes (null for new products)
- `json_after` (JSONB, NOT NULL) - Current product state from B2B
- `blocking_reason_id` (UUID, FK) - Reference to blocking reason
- `moderator_id` (UUID, nullable) - Moderator who took the card or made decision
- `moderator_comment` (TEXT, nullable) - Moderator's comment
- `date_created`, `date_updated`, `date_moderation` (TIMESTAMP) - Timestamps

**Constraints**:
- Unique constraint on `product_id`
- Check constraint on `status` (valid values)
- Check constraint on `queue_priority` (1-4)
- Foreign key to `product_blocking_reasons`

**Relationships**:
- `blocking_reason` - Many-to-one with ProductBlockingReason
- `field_reports` - One-to-many with ProductModerationFieldReport (cascade delete)

### 2. ProductModerationFieldReport (`product_moderation_field_report.py`)

Field-level reports for specific moderation issues.

**Table**: `product_moderation_field_report`

**Key Fields**:
- `id` (UUID, PK) - Record identifier
- `product_moderation_id` (UUID, FK, NOT NULL) - Reference to moderation record
- `field_name` (VARCHAR, NOT NULL) - Field with issue: title, description, product_images, category, sku_name, sku_image, sku_price
- `sku_id` (UUID, nullable) - Specific SKU ID (null = product-level issue)
- `comment` (TEXT, NOT NULL) - Issue description
- `date_created` (TIMESTAMP) - Creation timestamp

**Constraints**:
- Check constraint on `field_name` (valid values)
- Foreign key to `product_moderation` with CASCADE delete

### 3. ProductBlockingReason (`product_blocking_reasons.py`)

Reference table for predefined blocking reasons.

**Table**: `product_blocking_reasons`

**Key Fields**:
- `id` (UUID, PK) - Record identifier
- `title` (VARCHAR(255), NOT NULL) - Blocking reason text
- `hard_block` (BOOLEAN, NOT NULL, DEFAULT FALSE) - True = permanent block

**Seed Data**: 10 predefined reasons (7 soft blocks, 3 hard blocks)

## Usage

### Setup Database Connection

```python
from models.database import async_session_factory, init_db, seed_blocking_reasons

# Initialize database tables
await init_db()

# Seed blocking reasons
async with async_session_factory() as session:
    await seed_blocking_reasons(session)
    await session.commit()
```

### Example: Create Moderation Record

```python
from models.product_moderation import ProductModeration
from models.database import async_session_factory
import uuid

async with async_session_factory() as session:
    moderation = ProductModeration(
        product_id=uuid.UUID("..."),
        seller_id=uuid.UUID("..."),
        status="PENDING",
        queue_priority=1,
        json_after={...},  # Product data from B2B
    )
    session.add(moderation)
    await session.commit()
```

### Example: Query Pending Products

```python
from sqlalchemy import select
from models.product_moderation import ProductModeration

async with async_session_factory() as session:
    query = (
        select(ProductModeration)
        .where(ProductModeration.status == "PENDING")
        .where(ProductModeration.queue_priority == 1)
        .order_by(ProductModeration.date_updated.asc())
        .limit(1)
    )
    result = await session.execute(query)
    pending_product = result.scalar_one_or_none()
```

## Migration

SQL migration script is available in `migration.sql`. To apply:

```bash
psql -U user -d neomarket_moderation -f models/migration.sql
```

## State Machine

Product moderation follows this state machine:

```
PENDING ──► IN_REVIEW ──► MODERATED
                    └──► BLOCKED ──► (EDITED) ──► PENDING
                    └──► HARD_BLOCKED (terminal)
```

### Queue Priorities

| Priority | Name | Condition | Sort |
|----------|------|-----------|------|
| 1 | New products | `status = 'PENDING' AND date_moderation IS NULL` | `date_updated ASC` |
| 2 | Fixed after block | `status = 'PENDING' AND date_moderation IS NOT NULL AND blocking_reason_id IS NOT NULL` | `date_updated ASC` |
| 3 | Modified, in stock | `status = 'PENDING' AND date_moderation IS NOT NULL AND blocking_reason_id IS NULL AND total_active_quantity > 0` | `date_updated ASC` |
| 4 | Modified, out of stock | `status = 'PENDING' AND date_moderation IS NOT NULL AND blocking_reason_id IS NULL AND total_active_quantity = 0` | `date_updated ASC` |

## Conventions

- All IDs are UUID format
- All timestamps are timezone-aware
- JSON fields use snake_case
- Database fields use snake_case
- Comments in Russian (following project convention)
- SQLAlchemy 2.0 mapped_column() style
- Async session management

## Files

- `__init__.py` - Model exports
- `base.py` - SQLAlchemy declarative base
- `database.py` - Database configuration and session management
- `product_moderation.py` - Main moderation model
- `product_moderation_field_report.py` - Field report model
- `product_blocking_reasons.py` - Blocking reasons model with seed data
- `migration.sql` - SQL migration script
- `README.md` - This file

## References

- [Moderation Flows](../../flows/moderation-flows.md) - Complete flow specification
- [Events Schema](../../flows/events-schema.md) - Event format specification
- [B2B Flows](../../flows/b2b-flows.md) - B2B API specification