# ADR-001: Product Snapshot Strategy for Moderation

## Status

**Accepted** — 2024-01-18

## Context

The Moderation service needs to store product data snapshots to enable:
- Moderators to see product state at the time of submission
- Incident diagnosis when moderation decisions are questioned
- Audit trail for compliance and debugging

We must choose how to store product data changes when B2B sends EDITED events.

## Decision

**Chosen: Dual Snapshot (`json_before` + `json_after`)**

We will store both the previous state (`json_before`) and current state (`json_after`) of the product when processing EDITED events.

## Options Considered

### Option 1: Dual Snapshot (`json_before` + `json_after`) ✅ CHOSEN

**Description:**
Store complete product data snapshots for both before and after states.

**Example Schema:**
```sql
CREATE TABLE product_moderation (
    id UUID PRIMARY KEY,
    product_id UUID UNIQUE NOT NULL,
    json_before JSONB,          -- Previous state (NULL for new products)
    json_after JSONB NOT NULL,  -- Current state
    ...
);
```

**Example Data:**
```json
{
  "json_before": {
    "title": "Old Product Name",
    "price": 99.99,
    "skus": [{"id": "...", "name": "SKU A", "price": 99.99}]
  },
  "json_after": {
    "title": "New Product Name",
    "price": 149.99,
    "skus": [{"id": "...", "name": "SKU A", "price": 149.99}]
  }
}
```

**Pros:**
- ✅ **Incident Diagnosis**: Complete picture of what changed without reconstruction
- ✅ **Moderator UX**: Can directly compare before/after side-by-side
- ✅ **Simplicity**: No computation needed to understand changes
- ✅ **Audit Trail**: Full historical record for compliance
- ✅ **Debugging**: Easy to see exact state at any point in time
- ✅ **Already Implemented**: Schema and code already support this approach

**Cons:**
- ❌ **DB Space**: Stores duplicate data (mitigated by JSONB compression)
- ❌ **Storage Growth**: ~2x storage compared to single snapshot

**DB Space Analysis:**
- Average product JSON size: ~2-5 KB
- With JSONB compression: ~1-2 KB per snapshot
- Dual snapshot: ~2-4 KB per EDITED event
- Estimated 100K products/year × 3 edits/year × 4 KB = ~1.2 GB/year
- **Verdict**: Acceptable for modern storage systems

---

### Option 2: Single Snapshot (`json_after` only)

**Description:**
Only store the current state. Historical data is lost on each update.

**Example Schema:**
```sql
CREATE TABLE product_moderation (
    id UUID PRIMARY KEY,
    product_id UUID UNIQUE NOT NULL,
    json_before JSONB,          -- Always NULL
    json_after JSONB NOT NULL,  -- Current state (overwritten on EDIT)
    ...
);
```

**Pros:**
- ✅ **DB Space**: Minimal storage (~50% of dual snapshot)
- ✅ **Simplicity**: Less data to manage

**Cons:**
- ❌ **Incident Diagnosis**: Cannot reconstruct what changed without external logs
- ❌ **Moderator UX**: No context for what was modified
- ❌ **Audit Trail**: Incomplete - loses historical state
- ❌ **Debugging**: Must query B2B logs to understand previous state
- ❌ **Data Loss**: Previous state permanently lost on EDIT

**Risk Assessment:**
If a moderator blocks a product incorrectly, we cannot prove what the product looked like before the block without querying external systems.

---

### Option 3: Delta (Only Differences)

**Description:**
Store only the changed fields between states.

**Example Schema:**
```sql
CREATE TABLE product_moderation (
    id UUID PRIMARY KEY,
    product_id UUID UNIQUE NOT NULL,
    json_before JSONB,          -- Always NULL
    json_after JSONB NOT NULL,  -- Current state
    ...
);

CREATE TABLE product_moderation_snapshots (
    id UUID PRIMARY KEY,
    product_moderation_id UUID FK,
    delta JSONB NOT NULL,       -- Only changed fields
    created_at TIMESTAMP
);
```

**Example Delta:**
```json
{
  "delta": {
    "title": {
      "old": "Old Product Name",
      "new": "New Product Name"
    },
    "price": {
      "old": 99.99,
      "new": 149.99
    }
  }
}
```

**Pros:**
- ✅ **DB Space**: Minimal storage (only changes stored)
- ✅ **Granularity**: Explicit change tracking

**Cons:**
- ❌ **Incident Diagnosis**: Must reconstruct full state from delta chain
- ❌ **Moderator UX**: Cannot see full context without reconstruction
- ❌ **Complexity**: Requires delta computation logic
- ❌ **Performance**: Must apply multiple deltas to reconstruct state
- ❌ **Edge Cases**: Handling nested objects, arrays is complex
- ❌ **Debugging**: Harder to understand full picture

**Complexity Analysis:**
- Delta computation for nested JSON: O(n) where n = depth × fields
- Array diffing (e.g., SKUs): Requires custom logic
- Reconstruction: Must apply all deltas in sequence
- **Verdict**: High complexity for marginal storage savings

---

## Decision Rationale

### 1. DB Space (Weight: Medium)

| Option | Storage/Year | Relative Cost |
|--------|--------------|---------------|
| Dual Snapshot | ~1.2 GB | 1.0x |
| Single Snapshot | ~0.6 GB | 0.5x |
| Delta | ~0.3 GB | 0.25x |

**Analysis:**
- Storage is cheap ($0.023/GB/month for S3)
- 1.2 GB/year = ~$0.33/month
- **Conclusion**: Storage cost is negligible for the value provided

### 2. Incident Diagnosis (Weight: Critical)

| Option | Diagnosis Capability | Time to Diagnose |
|--------|---------------------|------------------|
| Dual Snapshot | Complete - direct comparison | Minutes |
| Single Snapshot | Incomplete - requires external logs | Hours |
| Delta | Complex - must reconstruct | 30+ minutes |

**Analysis:**
- When a seller appeals a block, we need to quickly understand what happened
- Dual snapshot allows immediate side-by-side comparison
- Single snapshot requires querying B2B audit logs (if available)
- Delta requires reconstructing state from multiple records

**Example Incident:**
> "Seller claims product was incorrectly blocked. What did the product look like before the block?"

- **Dual Snapshot**: Query moderation record → see both states instantly
- **Single Snapshot**: Query B2B logs → wait for response → correlate data
- **Delta**: Query all deltas → reconstruct state → hope chain is complete

**Conclusion**: Dual snapshot is essential for fast incident resolution

### 3. Moderator UX (Weight: High)

| Option | UX Quality | Implementation Effort |
|--------|-----------|----------------------|
| Dual Snapshot | Excellent - side-by-side view | Low |
| Single Snapshot | Poor - no context | Low |
| Delta | Good - but requires reconstruction | High |

**Analysis:**
- Moderators need to understand what changed to make informed decisions
- Side-by-side comparison is industry standard (GitHub diff, etc.)
- Dual snapshot enables simple UI implementation
- Delta requires complex UI to show reconstructed states

**UI Mockup (Dual Snapshot):**
```
┌─────────────────────────────────────────────────────────┐
│ Product: Test Product                                   │
├────────────────────────┬────────────────────────────────┤
│ BEFORE                 │ AFTER                          │
├────────────────────────┼────────────────────────────────┤
│ Title: Old Name        │ Title: New Name ← CHANGED      │
│ Price: $99.99          │ Price: $149.99 ← CHANGED       │
│ Images: [img1.jpg]     │ Images: [img2.jpg] ← CHANGED   │
└────────────────────────┴────────────────────────────────┘
```

**Conclusion**: Dual snapshot provides best moderator experience

---

## Consequences

### Positive
- Fast incident diagnosis and resolution
- Simple moderator UI implementation
- Complete audit trail for compliance
- No data loss on EDITED events
- Already implemented in current schema

### Negative
- ~2x storage compared to single snapshot (mitigated by JSONB compression)
- Slightly larger database backups

### Neutral
- Requires JSONB column type (already standard in PostgreSQL)
- No additional application logic needed

---

## Implementation Notes

### Current Implementation
```python
# On EDITED event:
moderation.json_before = moderation.json_after  # Previous state
moderation.json_after = cleaned_data            # New state
```

### Storage Optimization
PostgreSQL JSONB automatically compresses data:
- Whitespace removal
- Key deduplication
- Binary storage format

### Query Examples

**Get current state:**
```sql
SELECT json_after FROM product_moderation WHERE product_id = ?;
```

**Get previous state:**
```sql
SELECT json_before FROM product_moderation WHERE product_id = ?;
```

**Compare states (application-level):**
```python
before = moderation.json_before
after = moderation.json_after
changes = {k: after[k] for k in after if before.get(k) != after[k]}
```

---

## Related Decisions

- **ADR-002**: Queue Priority Calculation (pending)
- **ADR-003**: Field Report Storage Strategy (pending)

---

## References

- [PostgreSQL JSONB Documentation](https://www.postgresql.org/docs/current/datatype-json.html)
- [SQLAlchemy JSONB Type](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#json-jsonb)
- Industry best practices: GitHub, GitLab use dual snapshot for diffs

---

## Decision Log

| Date | Author | Decision |
|------|--------|----------|
| 2024-01-18 | Moderation Team | Accepted dual snapshot approach |

---

## Appendix: Storage Calculation

**Assumptions:**
- 100,000 products moderated per year
- Average 3 edits per product per year
- Average product JSON size: 3 KB
- JSONB compression ratio: 50%

**Calculation:**
```
Per edit: 2 snapshots × 3 KB × 0.5 compression = 3 KB
Per year: 100K products × 3 edits × 3 KB = 900 MB ≈ 1 GB
```

**Cost:**
- AWS RDS PostgreSQL: $0.023/GB/month
- 1 GB × $0.023 = $0.023/month
- **Annual cost: ~$0.28**

**Conclusion**: Storage cost is negligible for the business value provided.