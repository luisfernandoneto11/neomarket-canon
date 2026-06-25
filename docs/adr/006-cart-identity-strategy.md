# ADR-006: Cart Identity Strategy (Auth + Guest + Merge)

## Status

**Accepted** — 2026-06-25

## Context

The B2C Cart service must support both authenticated users and guest shoppers. Guests identify their cart via a `session_id` header; authenticated users use a `Bearer` token (mapped to `user_id`).

Key requirements:
- Guest adds items without authentication
- On login, guest cart must merge into the authenticated user's cart
- One active cart per identity (user or session)
- IDOR protection: users cannot access other users' carts, sessions cannot access other sessions' carts

## Decision

**Chosen: Dual-identity with session fallback + MAX merge**

Carts are owned by either a `user_id` (authenticated) or `session_id` (guest), never both. Lookup preference: `user_id` first, then `session_id`. On merge, quantities for the same SKU use `MAX(guest_qty, auth_qty)` (not sum).

### Identity Resolution

1. If `user_id` is provided → find or create cart by `user_id`
2. If no `user_id` → find or create cart by `session_id`
3. A cart can only have ONE identity (user_id OR session_id, never both)

### Merge Strategy (Guest → Auth)

When a guest logs in:
1. Find guest cart by `session_id`
2. Find auth cart by `user_id`
3. For each item in guest cart:
   - If SKU exists in auth cart → set `quantity = MAX(guest_qty, auth_qty)`
   - If SKU does NOT exist in auth cart → create new item with guest's quantity
4. Delete guest cart (or keep as empty)
5. Return merged auth cart

## Options Considered

### Option 1: Dual-identity with MAX merge ✅ CHOSEN

**Description:**
Carts are owned by user_id or session_id. On merge, use `MAX()` for overlapping SKUs.

**Example:**
```
Guest cart: SKU-A x2, SKU-B x1
Auth cart:  SKU-A x5, SKU-C x3
Result:     SKU-A x5, SKU-B x1, SKU-C x3
```

**Pros:**
- ✅ **User-friendly**: User keeps highest quantity they intended
- ✅ **Non-destructive**: No items lost during merge
- ✅ **Simple logic**: `MAX()` is commutative and idempotent
- ✅ **Single cart per identity**: No duplication
- ✅ **Clear ownership**: One cart per user or session

**Cons:**
- ❌ If user truly wants to add guest quantity to auth quantity (sum), they must manually adjust
- ❌ Guest cart is deleted after merge (could be kept but adds complexity)

---

### Option 2: Dual-identity with SUM merge

**Description:**
On merge, quantities for the same SKU are **summed**.

**Example:**
```
Guest cart: SKU-A x2, SKU-B x1
Auth cart:  SKU-A x5, SKU-C x3
Result:     SKU-A x7, SKU-B x1, SKU-C x3
```

**Pros:**
- ✅ **Additive**: Guest's items are "added" to user's cart

**Cons:**
- ❌ **Surprising behavior**: User who had SKU-A x5 and came back with SKU-A x2 gets x7 (unexpected)
- ❌ **Duplicate risk**: User may not realize they already had the SKU in their cart
- ❌ **Harder to undo**: After merge, reducing quantity requires knowing the original values

---

### Option 3: Dual-identity with separate carts, no merge

**Description:**
Guest and auth carts remain separate. On login, user keeps their auth cart; guest cart is abandoned.

**Pros:**
- ✅ **Simplest implementation**: No merge logic needed
- ✅ **No surprises**: Cart contents are independent

**Cons:**
- ❌ **Poor UX**: Items added as guest are lost on login
- ❌ **User frustration**: "I added items before logging in and they disappeared!"
- ❌ **Abandonment**: High cart abandonment rate if items are lost

---

## Decision Rationale

### 1. Merge necessity (Weight: Critical)

Users commonly add items to cart before logging in. Losing those items on login creates unacceptable UX.

**User journey:**
```
1. User browses as guest → adds 3 items
2. User clicks "Checkout" → prompted to login
3. User logs in → "Welcome back! Your cart has 3 items"
```

Without merge, step 3 shows "Your cart is empty" → frustration → abandonment.

### 2. MAX vs SUM (Weight: High)

| Scenario | SUM | MAX |
|----------|-----|-----|
| User had x5, guest added x2 → logs in | x7 (unexpected) | x5 (as expected) |
| User had x5, guest added x10 → logs in | x15 (unexpected) | x10 (as expected) |
| Users wants to add guest items to existing | Natural | Requires manual adjustment |

**Analysis:**
- SUM is natural for "I want to buy BOTH" but this is rare
- MAX is natural for "I want this many, whichever is more" which is the common case
- SUM can result in unexpectedly high quantities
- MAX is the "safe" choice that prevents over-ordering

### 3. Single vs dual cart per identity (Weight: Medium)

| Approach | Carts per identity | Pros | Cons |
|----------|-------------------|------|------|
| Single active cart | 1 | Simple, predictable | User loses previous carts |
| Multiple carts | N | History, restore | Complexity, confusion |

**Decision**: Single active cart per identity. Previous carts can be queried historically but the user always has ONE active cart.

---

## Consequences

### Positive
- Seamless guest-to-auth transition
- No items lost on login
- Single active cart per identity (predictable)
- IDOR protection by default (identity-based scoping)
- Merge is idempotent (re-merging same session is safe)

### Negative
- MAX merge may underestimate intended quantity in edge cases
- Guest cart deleted after merge (could confuse if same session continues)

### Neutral
- Requires `session_id` header for unauthenticated endpoints
- Merge endpoint requires both `Authorization` (Bearer) and `X-Session-Id`

---

## Implementation Notes

### Ownership Rules

```python
# User identity: find/create by user_id
cart = await service.get_or_create_cart(user_id="uuid-123")

# Guest identity: find/create by session_id
cart = await service.get_or_create_cart(session_id="sess-abc")

# Priority: user_id first
cart = await service.get_or_create_cart(user_id="uuid-123", session_id="sess-abc")
# → finds by user_id, session_id ignored
```

### Merge Endpoint

```
POST /api/v1/b2c/cart/merge
Headers: Authorization: Bearer {user_id}, X-Session-Id: {guest_session_id}
Response: Merged auth cart
```

### IDOR Protection

- All cart queries filter by `user_id` OR `session_id`
- User A cannot see User B's cart (different user_id)
- Session A cannot see Session B's cart (different session_id)
- All endpoints require EITHER `Authorization` or `X-Session-Id`
- Missing both headers → 401

### Cart Response Schema

```json
{
  "id": "cart-uuid",
  "user_id": "user-uuid",
  "items": [
    {
      "sku_id": "sku-uuid",
      "quantity": 3,
      "unavailable_reason": null,
      "sku_data": {
        "price": 29.99,
        "sku_code": "SKU-001",
        "product_name": "Test Product",
        "image_url": "https://...",
        "stock_quantity": 10
      }
    }
  ],
  "total_items": 3,
  "total_amount": 8997
}
```

**Notes:**
- `total_items` counts ALL items (including unavailable) for display
- `total_amount` only includes available items
- `unavailable_reason`: `SKU_NOT_FOUND`, `OUT_OF_STOCK`, `PRODUCT_BLOCKED`, or `null`
- `sku_data`: `null` when SKU not found

### Unavailable Items Logic

| Condition | `unavailable_reason` | `sku_data` | Counts in `total_items` | Counts in `total_amount` |
|-----------|---------------------|------------|------------------------|------------------------|
| SKU exists, stock > 0, product MODERATED | `null` | Populated | Yes | Yes |
| SKU does not exist in DB | `SKU_NOT_FOUND` | `null` | No | No |
| SKU exists, stock = 0 | `OUT_OF_STOCK` | Populated | Yes | No |
| SKU exists, product BLOCKED | `PRODUCT_BLOCKED` | Populated | Yes | No |

---

## Related Decisions

- **ADR-001**: Product Snapshot Strategy for Moderation (for product data)
- **ADR-002**: Product GET View Strategy (for catalog enrichment)
- **ADR-004**: Stock Reservation Locking Strategy (for checkout flow)

---

## References

- [OWASP IDOR Prevention Guide](https://cheatsheetseries.owasp.org/cheatsheet/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)
- Industry examples: Amazon (persistent cart across devices), Shopify (guest-to-auth merge)

---

## Decision Log

| Date | Author | Decision |
|------|--------|----------|
| 2026-06-25 | Engineering | Accepted dual-identity with MAX merge strategy |

---

## Appendix: Merge Algorithm

```python
async def merge_carts(self, auth_cart, guest_cart):
    """Merge guest cart into auth cart using MAX for overlapping SKUs."""
    guest_items = await self.get_items(guest_cart.id)
    
    for guest_item in guest_items:
        existing_item = await self.find_item(auth_cart.id, guest_item.sku_id)
        
        if existing_item:
            # Use MAX for overlapping SKUs
            existing_item.quantity = max(existing_item.quantity, guest_item.quantity)
            await self.db_session.merge(existing_item)
        else:
            # Move guest item to auth cart
            new_item = CartItem(
                cart_id=auth_cart.id,
                sku_id=guest_item.sku_id,
                quantity=guest_item.quantity,
            )
            self.db_session.add(new_item)
    
    await self.db_session.commit()
    await self.db_session.refresh(auth_cart)
    return auth_cart
```

**Complexity:** O(n) where n = number of items in guest cart
**Atomicity:** Single transaction commit for all changes
**Idempotency:** Re-merging same guest cart produces same result (MAX is idempotent)