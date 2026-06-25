# ADR 003: Public Catalog Endpoint

## Status

Accepted

## Context

The NeoMarket platform needs a public catalog endpoint that allows end consumers (B2C users) to browse available products in the marketplace. Currently, the system has:

- A B2B API for sellers to manage products (`apis/b2b/products.py`)
- Product moderation workflows that track product status (DRAFT, IN_REVIEW, MODERATED, BLOCKED, HARD_BLOCKED)
- SKU management with pricing and inventory data
- Internal schemas for B2B operations (`schemas/b2b_schemas.py`)

The public catalog must:
1. Only show MODERATED products (approved for public viewing)
2. Exclude HARD_BLOCKED products (removed from catalog)
3. Not expose sensitive fields like `cost_price`
4. Support pagination for scalability
5. Exclude soft-deleted products (`deleted=True`)

## Decision

We will implement a public catalog endpoint with the following architecture:

### Endpoint: `GET /api/v1/products`

A public endpoint (no seller authentication required) that returns a paginated list of MODERATED products with their SKUs.

### Service Layer: `services/catalog_service.py`

Contains the business logic for querying the catalog:
- Filters products by `status=MODERATED`
- Excludes `deleted=True` products
- Excludes `HARD_BLOCKED` products
- Applies pagination (limit/offset)
- Returns total count for pagination metadata

### Schemas: `schemas/catalog_schemas.py`

New Pydantic schemas specifically for catalog responses:
- `SKUCatalogResponse`: SKU data with id, sku_code, price, image_url, stock_quantity
- `ProductCatalogResponse`: Product data with id, name, description, status, skus
- `CatalogResponse`: Paginated response with items, total, limit, offset

### Router: `apis/b2b/catalog.py`

FastAPI router mounted at `/api/v1/products` that:
- Handles GET requests
- Depends on `services/catalog_service.py` for business logic
- Returns `CatalogResponse` schema

### Key Design Decisions

1. **Schema Separation**: We created dedicated catalog schemas (`schemas/catalog_schemas.py`) instead of reusing B2B schemas to ensure:
   - No sensitive data leakage (cost_price excluded)
   - Clean API contracts for public consumers
   - Independent evolution of B2B and public APIs

2. **Router Location**: Placed in `apis/b2b/` namespace since it follows the same API prefix convention, but functions as a public endpoint without auth requirements.

3. **Query Filters**:
   - Only `MODERATED` status products are shown
   - `HARD_BLOCKED` products are excluded (permanently removed from catalog)
   - Soft-deleted products (`deleted=True`) are excluded

4. **Pagination**: Standard limit/offset pagination for scalability.

## Consequences

### Positive
- Clean separation between B2B (seller-facing) and public (consumer-facing) APIs
- Sensitive data like `cost_price` is never exposed in public catalog
- Paginated responses ensure scalability with large product catalogs
- Dedicated schemas allow independent evolution

### Negative
- Additional schemas to maintain
- Catalog queries run against the same product tables, which could impact performance at scale

### Mitigations
- Consider adding database indexes on `status` and `deleted` fields for catalog queries
- Future optimization: read replicas or caching layer for catalog queries

## Related

- ADR 001: Product Snapshot Strategy
- ADR 002: Product GET View Strategy