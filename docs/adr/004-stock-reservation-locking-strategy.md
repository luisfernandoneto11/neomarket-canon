# ADR 004: Stock Reservation Locking Strategy

## Status

Accepted

## Context

The NeoMarket platform requires a stock reservation system that allows B2B sellers to reserve inventory for orders. This system must handle concurrent reservation requests safely while maintaining data consistency.

The stock reservation system has the following requirements:
1. **Atomicity**: Reservation operations must be all-or-nothing (either all items are reserved, or none)
2. **Consistency**: The invariant `active_quantity + reserved_quantity = on_hand` must always hold
3. **Isolation**: Concurrent reservations must not interfere with each other
4. **Idempotency**: Duplicate requests with the same `idempotency_key` should not result in double deductions

The system uses PostgreSQL as the primary database with SQLAlchemy async ORM.

## Decision

We will use **SELECT FOR UPDATE** (pessimistic locking) for stock reservation operations.

### Implementation

```python
async def _get_sku_with_lock(self, sku_id: str) -> Optional[SKU]:
    query = (
        select(SKU)
        .where(SKU.id == sku_id)
        .with_for_update()
    )
    result = await self.session.execute(query)
    return result.scalars().first()
```

All SKU reads within a reservation transaction use `with_for_update()` to acquire row-level locks, preventing other transactions from modifying the same SKUs until the current transaction commits or rolls back.

## Alternatives Considered

### 1. Optimistic Locking with Retry

**How it works**: Add a `version` column to the SKU table. On update, check that the version hasn't changed. If it has, retry the operation.

**Pros**:
- No database locks held during reads
- Higher throughput for read-heavy workloads
- No deadlocks possible

**Cons**:
- Complex retry logic in application code
- Under high contention, retries can cascade and degrade performance
- Version column adds schema complexity
- Harder to reason about correctness

**Verdict**: Rejected. While optimistic locking can improve throughput in read-heavy scenarios, stock reservation is write-heavy and requires strong consistency guarantees. The retry complexity outweighs any benefits.

### 2. Two-Phase Commit (2PC)

**How it works**: Prepare phase locks resources and checks constraints. Commit phase applies changes only if all prepares succeed.

**Pros**:
- Standard distributed transaction protocol
- Well-understood failure modes
- Can span multiple databases/services

**Cons**:
- Significant implementation complexity
- Requires transaction coordinator
- Blocking protocol (locks held during prepare phase)
- Overkill for single-database operations
- Hard to debug and recover from failures

**Verdict**: Rejected. 2PC is designed for distributed transactions across multiple databases. Our reservation operations are contained within a single PostgreSQL database, making 2PC unnecessarily complex.

### 3. SELECT FOR UPDATE (Chosen)

**How it works**: Acquire exclusive row locks on all SKUs before reading and modifying them. Locks are released on commit/rollback.

**Pros**:
- Simple implementation (built into SQLAlchemy via `with_for_update()`)
- Real atomicity - locks prevent concurrent modifications
- No retry logic needed
- Easy to reason about correctness
- PostgreSQL handles deadlock detection automatically

**Cons**:
- Locks can reduce concurrency
- Potential for deadlocks (mitigated by consistent lock ordering)
- Blocking waits under high contention

**Verdict**: Chosen. The simplicity, correctness guarantees, and native database support make SELECT FOR UPDATE the best fit for our stock reservation system.

## Criteria Evaluation

| Criterion | SELECT FOR UPDATE | Optimistic + Retry | Two-Phase Commit |
|-----------|------------------|-------------------|------------------|
| Performance under contention | Medium | High (low contention) / Low (high contention) | Low |
| Implementation complexity | Low | Medium | High |
| Consistency guarantee | Strong | Strong (with retry) | Strong |
| Debuggability | Easy | Medium | Hard |
| Deadlock risk | Low (managed by PG) | None | Medium |

## Consequences

### Positive
- **Correctness**: Guarantees that concurrent reservations cannot oversell inventory
- **Simplicity**: Minimal application code; database handles concurrency control
- **Atomicity**: Natural fit with SQL transactions - commit/rollback semantics are clear
- **Debuggability**: Easy to trace and understand lock behavior

### Negative
- **Lock contention**: Under very high concurrency, transactions may wait for locks
- **Deadlock potential**: If lock ordering is inconsistent (mitigated by sorting SKU IDs before locking)

### Mitigations
- Keep transactions short to minimize lock hold time
- Sort SKU IDs before acquiring locks to prevent deadlocks
- Monitor for lock waits and tune `lock_timeout` as needed
- Consider connection pooling to handle concurrent requests efficiently

## Related

- ADR 001: Product Snapshot Strategy
- ADR 002: Product GET View Strategy
- ADR 003: Public Catalog Endpoint