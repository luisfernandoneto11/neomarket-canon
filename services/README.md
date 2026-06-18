# Services for NeoMarket Moderation

This directory contains business logic services for the moderation module.

## Overview

Services handle the core business logic for processing product events,
calculating queue priorities, and managing moderation workflows.

## Files

### 1. `product_event_service.py`

Core service for processing product events from B2B.

**Helper Functions:**

- `strip_private_fields(product_data)` - Removes internal fields (cost_price, reserved_quantity)
- `calculate_total_active_quantity(product_data)` - Sums active inventory across SKUs
- `calculate_queue_priority(product_data, moderation)` - Determines queue priority (1-4)

**Event Handlers:**

- `process_created_event()` - Creates new PENDING moderation record
- `process_edited_event()` - Updates existing record, recalculates priority
- `process_deleted_event()` - Removes moderation record
- `check_idempotency()` - Prevents duplicate event processing

## Queue Priority Logic

| Priority | Condition |
|----------|-----------|
| 1 | New product (no previous moderation) |
| 2 | Previously blocked (has blocking_reason_id) |
| 3 | Previously moderated, in stock (total_active_quantity > 0) |
| 4 | Previously moderated, out of stock (total_active_quantity = 0) |

## Private Fields

The following fields are stripped from product data before storage:
- `cost_price`
- `reserved_quantity`

This ensures sensitive pricing information is not stored in moderation records.

## Idempotency

Events are idempotent based on `(product_id, date)` combination.
If an event with the same product_id and a later or equal date has already been processed, the event is skipped.

## Usage Example

```python
from services.product_event_service import process_created_event, strip_private_fields

# Clean product data
cleaned_data = strip_private_fields(raw_product_data)

# Process event
moderation = await process_created_event(
    session,
    product_id,
    seller_id,
    cleaned_data
)
```

## Future Implementation

- `fetch_product_from_b2b()` - HTTP client for B2B API (requires implementation)
- Integration with external services for notifications
- Metrics and monitoring hooks