# ADR-005: Moderation Events Endpoint with Idempotency and Soft/Hard Block

## Status

Accepted

## Context

The NeoMarket Moderation Service needs to receive moderation decisions from an external B2B service via webhook. The external service sends decisions via HTTP POST with different statuses (MODERATED, BLOCKED) and block types (soft/hard). The endpoint must:

1. **Authenticate requests** using a service-to-service `X-Service-Key` header
2. **Support idempotency** to ensure retries from the external service don't cause duplicate effects
3. **Apply state transitions** to products:
   - MODERATED: clears blocking data (blocking_reason, field_reports)
   - BLOCKED (soft): saves blocking data and triggers product_event_service
   - BLOCKED (hard): same as soft but sets terminal HARD_BLOCKED status
4. **Enforce access control**: HARD_BLOCKED products reject seller edits (PUT/DELETE returns 403)
5. **Store moderation events** for audit trail

The endpoint receives events with:
- `idempotency_key`: UUID for deduplication
- `product_id`: product being moderated
- `status`: MODERATED or BLOCKED
- `hard_block`: boolean for hard block (only when BLOCKED)
- `blocking_reason`: optional reason object
- `field_reports`: optional array of field reports

## Decision

### 1. Endpoint Design

| Aspect | Decision |
|--------|----------|
| URL | `POST /api/v1/events/moderation` |
| Service key | `X-Service-Key` header (required) |
| Success response | 200 with `{ ok: true }` |
| Product not found | 404 |
| Invalid data | 400 |
| Missing/invalid key | 401 |

### 2. Authentication

Simple service-to-service key validation. This is a webhook endpoint, not a user-facing endpoint. Authentication validates that requests originate from the authorized B2B service. The key is validated in the handler itself (not as a FastAPI dependency) to keep the endpoint simple.

### 3. Idempotency (INSERT-before-processing)

#### 3.1 Alternatives Considered

| # | Alternative | Advantages | Disadvantages |
|---|-------------|------------|---------------|
| 1 | **`moderation_events` table with idempotency_key as PK** (chosen) | Full audit trail; Easy debug; No race conditions (DB enforces PK constraint); Each event recorded separately | Extra table in database |
| 2 | **`last_event_key` field on Product model** | No extra table; Atomic update with status | No history of past events; Loses information when multiple events occur; Harder to debug |
| 3 | **Conditional upsert in database** | Single operation; Lowest latency | Hard to debug (no per-event logs); Limited database support for complex conditions; No audit trail per event |

#### 3.2 Evaluation Criteria

| Criteria | `moderation_events` table | `last_event_key` on Product | Conditional upsert |
|----------|---------------------------|-----------------------------|---------------------|
| Race-condition risk | **Low** (DB PK constraint) | Medium (may overwrite recent event) | **Low** (ON CONFLICT) |
| Support complexity | **Low** (complete audit) | Medium (loses history) | High (no logs per event) |
| Debuggability | **High** (event record per key) | Medium (single field) | Low (when event fails, no record) |

#### 3.3 Decision: `moderation_events` table with INSERT-before-processing

**Order of operations:**
1. **INSERT** event record with `idempotency_key` as PRIMARY KEY
   - INSERT triggers `session.flush()` to enforce PK constraint immediately
   - If concurrent request with same key arrives, second INSERT raises `IntegrityError`
2. **CATCH** `IntegrityError` → rollback and return success (no side effects)
3. **SELECT** product by ID
4. **APPLY** moderation decision (MODERATED or BLOCKED)
5. **COMMIT** transaction (product update + event record committed together)

**Why this order?** Inserting the event FIRST ensures that even if two requests arrive simultaneously, only one will succeed in the INSERT. The second will fail with `IntegrityError` and return early without processing the moderation decision twice.

### 4. Status Transitions

| Current Status | Event Status | Soft/Hard | New Status | Side Effects |
|----------------|--------------|-----------|------------|--------------|
| Any | MODERATED | - | MODERATED | Clear blocking_reason, field_reports |
| Any | BLOCKED | Soft | BLOCKED | Save blocking data, send event to B2C |
| Any | BLOCKED | Hard | HARD_BLOCKED | Save blocking data, send event to B2C |

### 5. Conflict Resolution

If a product is currently IN_REVIEW (being moderated by an operator):
- Continue applying the event (log a warning)
- Does NOT raise a conflict error

### 6. HARD_BLOCKED Restrictions

When a product has status `HARD_BLOCKED`:
- PUT `/api/v1/products/{product_id}` returns 403
- DELETE `/api/v1/products/{product_id}` returns 403

Prevents sellers from modifying products that have been permanently blocked by external moderation.

### 7. New Files

```
apis/b2b/moderation_events.py          # Endpoint implementation
schemas/moderation_event_schemas.py    # Request/Response schemas
models/moderation_event.py             # Audit trail model
services/moderation_apply_service.py   # Business logic
tests/test_b2b_moderation_events.py    # 6 tests (one per scenario)
```

### 8. Configuration

Existing configuration:
- `B2B_SERVICE_KEY` in `apis/moderation/events.py`
- Database: shared PostgreSQL/SQLite instance

No new environment variables or configuration required.

## Consequences

### Positive
- Clear contract with external B2B service via endpoint + schemas
- Idempotency prevents duplicate side effects from retries
- Audit trail via `moderation_events` table
- HARD_BLOCKED restriction prevents seller manipulation of blocked products

### Negative
- Authentication is global key per service (not per-client)
- No public moderation supported

### Risks
- External service may send events in unexpected order (race conditions)
- Idempotency relies on unique `idempotency_key` per event
- IN_REVIEW status is not blocked, but logged as warning

## Related ADRs

- **ADR-001**: Product Snapshot Strategy - defines how snapshot data is stored
- **ADR-002**: Product GET View Strategy - defines how products are displayed by status
- **ADR-003**: Public Catalog Endpoint - defines public product listing
- **ADR-004**: Stock Reservation Locking Strategy - defines how stock is managed during transactions