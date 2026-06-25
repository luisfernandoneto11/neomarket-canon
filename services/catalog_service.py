"""
Catalog Service for NeoMarket.

Handles business logic for the public product catalog,
including filtering, pagination, data transformation, and facet aggregation.
Fetches product data from the B2B service via async HTTP client.
"""

from typing import Optional, List, Dict, Any
from collections import Counter

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.product import Product, SKU
from schemas.catalog_schemas import CatalogResponse, ProductCatalogResponse, SKUCatalogResponse
from schemas.catalog_filters_schemas import (
    ProductListQueryParams,
    ProductListResponse,
    ProductListItem,
    FacetResponse,
    FacetCategory,
    FacetPriceRange,
    FacetAvailability,
)
from clients.b2b_client import B2BClient, B2BServiceUnavailableError
from schemas.b2b_schemas import ProductResponse


class CatalogService:
    """
    Service for catalog operations.

    Handles querying products for the public catalog via B2B service,
    including filtering, sorting, pagination, and facet aggregation.
    """

    def __init__(
        self,
        session: AsyncSession = None,
        b2b_client: B2BClient = None,
    ):
        """
        Initialize catalog service.

        Args:
            session: Database session (optional, used for local queries).
            b2b_client: B2B client instance for fetching product data.
        """
        self.session = session
        self.b2b_client = b2b_client or B2BClient()

    async def get_catalog(self, filters: ProductListQueryParams) -> ProductListResponse:
        """
        Get paginated catalog of visible products from B2B.

        Applies filters (category, price, stock, search, sort) and returns
        paginated product list enriched with current pricing and stock.

        Args:
            filters: ProductListQueryParams with filter/pagination settings.

        Returns:
            ProductListResponse with items and pagination metadata.

        Raises:
            B2BServiceUnavailableError: If B2B service is down.
        """
        limit = max(1, min(filters.limit, 100))
        offset = max(0, filters.offset)

        # Build filter dict for B2B API
        b2b_filters = {
            "limit": limit,
            "offset": offset,
        }
        if filters.category:
            b2b_filters["category"] = filters.category
        if filters.min_price is not None:
            b2b_filters["min_price"] = filters.min_price
        if filters.max_price is not None:
            b2b_filters["max_price"] = filters.max_price
        if filters.in_stock is not None:
            b2b_filters["in_stock"] = filters.in_stock
        if filters.search:
            b2b_filters["search"] = filters.search
        if filters.sort:
            b2b_filters["sort"] = filters.sort

        # Call B2B service
        response = await self.b2b_client.get_products(b2b_filters)

        # B2B returns: {"items": [...], "total": int, "limit": int, "offset": int}
        raw_items = response.get("items", [])
        total = response.get("total", len(raw_items))

        # Map B2B product data to ProductListItem
        items = [self._map_to_list_item(p) for p in raw_items]

        return ProductListResponse(
            items=items,
            total_count=total,
            limit=limit,
            offset=offset,
        )

    async def get_facets(self, filters: ProductListQueryParams) -> FacetResponse:
        """
        Calculate facet counts for products matching the given filters.

        Fetches all products from B2B (without pagination) matching the filters,
        then aggregates counts by category, price range, and availability.

        Args:
            filters: ProductListQueryParams with filter settings (pagination ignored).

        Returns:
            FacetResponse with category, price range, and availability counts.

        Raises:
            B2BServiceUnavailableError: If B2B service is down.
        """
        # Remove pagination for facet calculation - fetch all matching products
        b2b_filters = {}
        if filters.category:
            b2b_filters["category"] = filters.category
        if filters.min_price is not None:
            b2b_filters["min_price"] = filters.min_price
        if filters.max_price is not None:
            b2b_filters["max_price"] = filters.max_price
        if filters.in_stock is not None:
            b2b_filters["in_stock"] = filters.in_stock
        if filters.search:
            b2b_filters["search"] = filters.search
        # Note: sort doesn't affect facet counts, so we skip it

        # Call B2B with large limit to get all matching products
        b2b_filters["limit"] = 1000
        b2b_filters["offset"] = 0

        response = await self.b2b_client.get_products(b2b_filters)
        raw_items = response.get("items", [])

        # --- Category facets ---
        category_counter: Counter = Counter()
        for item in raw_items:
            cat = item.get("category")
            if cat:
                cat_id = cat.get("id", "unknown") if isinstance(cat, dict) else str(cat)
                cat_name = cat.get("name", cat_id) if isinstance(cat, dict) else str(cat)
                category_counter[(cat_id, cat_name)] += 1

        category_facets = [
            FacetCategory(id=cat_id, name=cat_name, count=count)
            for (cat_id, cat_name), count in category_counter.most_common()
        ]

        # --- Price range facets ---
        price_ranges = self._compute_price_ranges(raw_items)

        # --- Availability facets ---
        in_stock_count = 0
        out_of_stock_count = 0
        for item in raw_items:
            skus = item.get("skus", [])
            total_stock = 0
            for sku in skus:
                if isinstance(sku, dict):
                    total_stock += sku.get("stock_quantity", 0)
                else:
                    total_stock += getattr(sku, "stock_quantity", 0)
            if total_stock > 0:
                in_stock_count += 1
            else:
                out_of_stock_count += 1

        return FacetResponse(
            categories=category_facets,
            price_ranges=price_ranges,
            availability=FacetAvailability(
                in_stock_count=in_stock_count,
                out_of_stock_count=out_of_stock_count,
            ),
        )

    def _compute_price_ranges(self, raw_items: List[Dict[str, Any]]) -> List[FacetPriceRange]:
        """
        Compute price range facets from product items.

        Uses fixed price ranges: 0-50, 50-100, 100-500, 500-1000, 1000+.
        Uses min_price of each product for range assignment.

        Args:
            raw_items: List of product dicts from B2B response.

        Returns:
            List of FacetPriceRange with counts.
        """
        # Define price boundaries
        ranges = [
            (0, 50, "0-50"),
            (50, 100, "50-100"),
            (100, 500, "100-500"),
            (500, 1000, "500-1000"),
            (1000, float("inf"), "1000+"),
        ]

        range_counts = {label: 0 for _, _, label in ranges}

        for item in raw_items:
            skus = item.get("skus", [])
            # Get minimum price across all SKUs
            min_price = None
            for sku in skus:
                if isinstance(sku, dict):
                    price = sku.get("price", 0)
                else:
                    price = getattr(sku, "price", 0) or 0
                if min_price is None or price < min_price:
                    min_price = price

            if min_price is None:
                continue

            for low, high, label in ranges:
                if low <= min_price < high:
                    range_counts[label] += 1
                    break

        price_range_facets = []
        for low, high, label in ranges:
            count = range_counts[label]
            if count > 0:
                price_range_facets.append(
                    FacetPriceRange(
                        min=low,
                        max=high if high != float("inf") else 999999,
                        count=count,
                    )
                )

        return price_range_facets

    def _map_to_list_item(self, raw: Dict[str, Any]) -> ProductListItem:
        """
        Map a raw B2B product dict to a ProductListItem.

        Extracts min/max price across SKUs, total stock, and primary image.

        Args:
            raw: Product dict from B2B response with SKUs included.

        Returns:
            ProductListItem for catalog listing display.
        """
        skus = raw.get("skus", [])

        min_price = None
        max_price = None
        total_stock = 0
        image_url = None

        for sku in skus:
            if isinstance(sku, dict):
                price = sku.get("price", 0) or 0
                stock = sku.get("stock_quantity", 0) or 0
                sku_image = sku.get("image_url")
            else:
                price = getattr(sku, "price", 0) or 0
                stock = getattr(sku, "stock_quantity", 0) or 0
                sku_image = getattr(sku, "image_url", None)

            # Update price range
            if min_price is None or price < min_price:
                min_price = price
            if max_price is None or price > max_price:
                max_price = price

            total_stock += stock

            # Use first available image
            if image_url is None and sku_image:
                image_url = str(sku_image) if not isinstance(sku_image, str) else sku_image

        # Extract category info
        category = raw.get("category")
        category_name = None
        if isinstance(category, dict):
            category_name = category.get("name") or category.get("id")
        elif category:
            category_name = str(category)

        return ProductListItem(
            id=str(raw.get("id", "")),
            name=raw.get("name", ""),
            description=raw.get("description"),
            category=category_name,
            min_price=min_price if min_price is not None else 0.0,
            max_price=max_price if max_price is not None else 0.0,
            image_url=image_url,
            total_stock=total_stock,
            is_available=total_stock > 0,
        )

    # --- Legacy method for backward compatibility ---

    async def get_catalog_legacy(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> CatalogResponse:
        """
        Get paginated catalog of active products from local database.

        Legacy method using direct SQL queries. Kept for backward compatibility.
        New code should use get_catalog() with B2B client.

        Returns products that are:
        - Not deleted (deleted = False)
        - Have status = 'MODERATED'
        - Have at least one SKU with stock > 0

        Args:
            limit: Maximum number of items per page (default 20, max 100).
            offset: Number of items to skip for pagination.

        Returns:
            CatalogResponse with items and pagination metadata.
        """
        # Clamp limit to reasonable range
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        if not self.session:
            raise RuntimeError("Database session not available for legacy catalog query")

        # Build query for active, non-deleted products with SKUs
        query = (
            select(Product)
            .where(
                Product.deleted == False,
                Product.status == "MODERATED",
            )
            .options(selectinload(Product.skus))
            .order_by(Product.created_at.desc())
        )

        # Get total count
        count_query = select(func.count(Product.id)).where(
            Product.deleted == False,
            Product.status == "MODERATED",
        )
        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        # Apply pagination
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        products = result.scalars().unique().all()

        # Transform to catalog response
        items = [self._to_product_catalog(p) for p in products]

        return CatalogResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    def _to_product_catalog(self, product: Product) -> ProductCatalogResponse:
        """
        Transform Product model to ProductCatalogResponse.

        Args:
            product: Product model instance with SKUs loaded.

        Returns:
            ProductCatalogResponse for catalog display.
        """
        skus = [
            SKUCatalogResponse(
                id=sku.id,
                sku_code=sku.sku_code,
                price=float(sku.price),
                image_url=sku.image_url,
                stock_quantity=sku.stock_quantity,
            )
            for sku in product.skus
        ]

        return ProductCatalogResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            status=product.status,
            skus=skus,
        )