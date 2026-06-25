"""
Catalog filter and facet schemas for B2C product listing.

Used in public catalog endpoints for query parameters, responses,
and facet/count aggregations.
"""

from typing import Optional, List

from pydantic import BaseModel, Field


class ProductListQueryParams(BaseModel):
    """
    Query parameters for the product list endpoint.

    Supports filtering, sorting, and pagination for the public catalog.
    """

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items per page (1-100)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip for pagination",
    )
    category: Optional[str] = Field(
        None,
        description="Filter by category slug or name",
    )
    min_price: Optional[float] = Field(
        None,
        ge=0,
        description="Minimum price filter",
    )
    max_price: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum price filter",
    )
    in_stock: Optional[bool] = Field(
        None,
        description="Filter by stock availability (true = in stock only)",
    )
    search: Optional[str] = Field(
        None,
        description="Full-text search on product name/description",
    )
    sort: Optional[str] = Field(
        None,
        description="Sort order: price_asc, price_desc, date_asc, date_desc, popularity",
    )


class ProductListItem(BaseModel):
    """
    Simplified product entry in a list response.

    Contains essential fields for catalog listing display.
    """

    id: str = Field(
        ...,
        description="Product UUID as string",
    )
    name: str = Field(
        ...,
        description="Product name",
    )
    description: Optional[str] = Field(
        None,
        description="Product description",
    )
    category: Optional[str] = Field(
        None,
        description="Product category",
    )
    min_price: float = Field(
        ...,
        description="Minimum price across all SKUs",
    )
    max_price: float = Field(
        ...,
        description="Maximum price across all SKUs",
    )
    image_url: Optional[str] = Field(
        None,
        description="Primary image URL (from first SKU)",
    )
    total_stock: int = Field(
        ...,
        description="Total stock across all SKUs",
    )
    is_available: bool = Field(
        ...,
        description="Whether product has at least one SKU in stock",
    )

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """
    Paginated response for the product list endpoint.
    """

    items: List[ProductListItem] = Field(
        ...,
        description="List of products matching the query",
    )
    total_count: int = Field(
        ...,
        description="Total number of products matching filters",
    )
    limit: int = Field(
        ...,
        description="Maximum number of items per page",
    )
    offset: int = Field(
        ...,
        description="Number of items skipped",
    )


class FacetCategory(BaseModel):
    """
    Single category facet with count.
    """

    id: str = Field(
        ...,
        description="Category identifier or slug",
    )
    name: str = Field(
        ...,
        description="Category display name",
    )
    count: int = Field(
        ...,
        description="Number of products in this category",
    )


class FacetPriceRange(BaseModel):
    """
    Single price range facet with count.
    """

    min: float = Field(
        ...,
        description="Minimum price in this range",
    )
    max: float = Field(
        ...,
        description="Maximum price in this range",
    )
    count: int = Field(
        ...,
        description="Number of products in this price range",
    )


class FacetAvailability(BaseModel):
    """
    Availability facet counts.
    """

    in_stock_count: int = Field(
        ...,
        description="Number of products with stock > 0",
    )
    out_of_stock_count: int = Field(
        ...,
        description="Number of products with no stock",
    )


class FacetResponse(BaseModel):
    """
    Response for the catalog facets endpoint.

    Provides aggregated counts for filtering UI.
    """

    categories: List[FacetCategory] = Field(
        default_factory=list,
        description="Category facets with counts",
    )
    price_ranges: List[FacetPriceRange] = Field(
        default_factory=list,
        description="Price range facets with counts",
    )
    availability: FacetAvailability = Field(
        ...,
        description="Availability counts",
    )