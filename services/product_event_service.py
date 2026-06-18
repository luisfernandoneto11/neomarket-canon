"""
Product Event Service for NeoMarket Moderation.

Handles business logic for processing product events from B2B,
including CREATED, EDITED, and DELETED events.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.product_moderation import ProductModeration
from models.product_moderation_field_report import ProductModerationFieldReport


# Fields to strip from product data (private/internal fields)
PRIVATE_FIELDS = {"cost_price", "reserved_quantity"}


def strip_private_fields(product_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove private/internal fields from product data before storing.
    
    Args:
        product_data: Raw product data from B2B API.
        
    Returns:
        Product data with private fields removed.
    """
    if not product_data:
        return {}
    
    # Create a copy to avoid modifying the original
    cleaned_data = product_data.copy()
    
    # Remove private fields
    for field in PRIVATE_FIELDS:
        cleaned_data.pop(field, None)
    
    # Also strip private fields from SKU data if present
    if "skus" in cleaned_data and isinstance(cleaned_data["skus"], list):
        cleaned_data["skus"] = [
            {k: v for k, v in sku.items() if k not in PRIVATE_FIELDS}
            for sku in cleaned_data["skus"]
        ]
    
    return cleaned_data


def calculate_total_active_quantity(product_data: Dict[str, Any]) -> int:
    """
    Calculate total active quantity across all SKUs.
    
    Active quantity = total_quantity - reserved_quantity (if present in raw data).
    If reserved_quantity is not present, uses total_quantity as active quantity.
    
    Args:
        product_data: Product data from B2B API.
        
    Returns:
        Total active quantity across all SKUs.
    """
    if not product_data:
        return 0
    
    total_active = 0
    skus = product_data.get("skus", [])
    
    if not isinstance(skus, list):
        return 0
    
    for sku in skus:
        if not isinstance(sku, dict):
            continue
        
        # Get total quantity
        total_qty = sku.get("total_quantity", 0)
        if not isinstance(total_qty, (int, float)):
            total_qty = 0
        
        # Get reserved quantity (may not be present after stripping)
        reserved_qty = sku.get("reserved_quantity", 0)
        if not isinstance(reserved_qty, (int, float)):
            reserved_qty = 0
        
        # Calculate active quantity
        active_qty = max(0, total_qty - reserved_qty)
        total_active += active_qty
    
    return total_active


def calculate_queue_priority(
    product_data: Dict[str, Any],
    moderation: Optional[ProductModeration] = None,
) -> int:
    """
    Calculate queue priority based on product state and moderation history.
    
    Priority rules:
    - 1: New product (no previous moderation)
    - 2: Previously blocked (has blocking_reason_id in history)
    - 3: Previously moderated, currently in stock (total_active_quantity > 0)
    - 4: Previously moderated, currently out of stock (total_active_quantity = 0)
    
    Args:
        product_data: Current product data from B2B API.
        moderation: Existing moderation record if any.
        
    Returns:
        Queue priority (1-4).
    """
    # If no existing moderation record, this is a new product
    if moderation is None:
        return 1
    
    # Check if product was previously blocked
    if moderation.blocking_reason_id is not None:
        return 2
    
    # Product was previously moderated, check stock
    total_active_quantity = calculate_total_active_quantity(product_data)
    
    if total_active_quantity > 0:
        return 3
    else:
        return 4


async def fetch_product_from_b2b(product_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """
    Fetch product data from B2B API.
    
    In production, this would make an HTTP request to B2B service.
    For now, returns a placeholder.
    
    Args:
        product_id: UUID of the product to fetch.
        
    Returns:
        Product data dictionary or None if not found.
    """
    # TODO: Implement actual HTTP call to B2B API
    # Example: GET /api/v1/products/{product_id}
    # This is a placeholder for the actual implementation
    raise NotImplementedError(
        "B2B API client not implemented. "
        "This should call GET /api/v1/products/{product_id} from B2B service."
    )


async def process_created_event(
    session: AsyncSession,
    product_id: uuid.UUID,
    seller_id: uuid.UUID,
    product_data: Dict[str, Any],
) -> ProductModeration:
    """
    Process CREATED event - create new PENDING moderation record.
    
    Args:
        session: Database session.
        product_id: Product UUID.
        seller_id: Seller UUID.
        product_data: Product data from B2B.
        
    Returns:
        Created ProductModeration record.
    """
    # Strip private fields
    cleaned_data = strip_private_fields(product_data)
    
    # Create new moderation record
    moderation = ProductModeration(
        product_id=product_id,
        seller_id=seller_id,
        status="PENDING",
        queue_priority=1,  # New products always priority 1
        json_before=None,  # No previous state for new products
        json_after=cleaned_data,
    )
    
    session.add(moderation)
    await session.flush()
    
    return moderation


async def process_edited_event(
    session: AsyncSession,
    product_id: uuid.UUID,
    seller_id: uuid.UUID,
    product_data: Dict[str, Any],
) -> Optional[ProductModeration]:
    """
    Process EDITED event - update existing record or create new one.
    
    Args:
        session: Database session.
        product_id: Product UUID.
        seller_id: Seller UUID.
        product_data: Updated product data from B2B.
        
    Returns:
        Updated ProductModeration record or None if not found.
    """
    # Find existing moderation record
    query = select(ProductModeration).where(
        ProductModeration.product_id == product_id
    )
    result = await session.execute(query)
    moderation = result.scalar_one_or_none()
    
    if moderation is None:
        # No existing record, create new one
        return await process_created_event(
            session, product_id, seller_id, product_data
        )
    
    # Strip private fields from new data
    cleaned_data = strip_private_fields(product_data)
    
    # Update existing record
    moderation.seller_id = seller_id
    moderation.json_before = moderation.json_after  # Previous state becomes "before"
    moderation.json_after = cleaned_data  # New state becomes "after"
    moderation.status = "PENDING"
    moderation.date_updated = datetime.utcnow()
    
    # Recalculate queue priority based on history and current state
    moderation.queue_priority = calculate_queue_priority(cleaned_data, moderation)
    
    # Clear blocking reason and moderator info for re-moderation
    moderation.blocking_reason_id = None
    moderation.moderator_id = None
    moderation.moderator_comment = None
    moderation.date_moderation = None
    
    # Delete all field reports (they're outdated)
    delete_query = delete(ProductModerationFieldReport).where(
        ProductModerationFieldReport.product_moderation_id == moderation.id
    )
    await session.execute(delete_query)
    
    await session.flush()
    
    return moderation


async def process_deleted_event(
    session: AsyncSession,
    product_id: uuid.UUID,
) -> bool:
    """
    Process DELETED event - remove moderation record.
    
    Args:
        session: Database session.
        product_id: Product UUID.
        
    Returns:
        True if record was deleted, False if not found.
    """
    # Find existing moderation record
    query = select(ProductModeration).where(
        ProductModeration.product_id == product_id
    )
    result = await session.execute(query)
    moderation = result.scalar_one_or_none()
    
    if moderation is None:
        return False
    
    # Delete the record (cascade will handle field reports)
    await session.delete(moderation)
    await session.flush()
    
    return True


async def check_idempotency(
    session: AsyncSession,
    product_id: uuid.UUID,
    event_date: datetime,
) -> bool:
    """
    Check if event was already processed (idempotency check).
    
    Uses (product_id, date) combination to detect duplicate events.
    
    Args:
        session: Database session.
        product_id: Product UUID.
        event_date: Event timestamp.
        
    Returns:
        True if event was already processed, False otherwise.
    """
    query = select(ProductModeration).where(
        ProductModeration.product_id == product_id,
        ProductModeration.date_updated >= event_date,
    )
    result = await session.execute(query)
    existing = result.scalar_one_or_none()
    
    return existing is not None