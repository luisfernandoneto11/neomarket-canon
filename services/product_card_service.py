"""
Product Card Service for B2C.

Handles business logic for fetching and enriching product data
from the B2B service for the B2C product card endpoint.
Ensures sensitive fields are never exposed to buyers.
"""

import logging
from typing import Optional

from clients.b2b_client import B2BClient, B2BClientError, B2BServiceUnavailableError
from schemas.product_card_schemas import (
    ProductCardResponse,
    SKUCardResponse,
    ProductImageResponse,
    CharacteristicResponse,
    CategoryResponse,
)

logger = logging.getLogger(__name__)


class ProductCardError(Exception):
    """Base exception for product card service errors."""
    pass


class ProductNotVisibleError(ProductCardError):
    """Raised when product is not visible to B2C (blocked, deleted, not moderated)."""
    pass


class ProductCardService:
    """
    Service for fetching product cards from B2B and preparing
    B2C-safe responses.
    
    Responsibilities:
    - Fetch product data from B2B service
    - Validate product visibility (MODERATED, not deleted, not blocked)
    - Strip sensitive fields (cost_price, reserved_quantity)
    - Calculate derived fields (in_stock)
    """

    def __init__(self, b2b_client: Optional[B2BClient] = None):
        """
        Initialize product card service.
        
        Args:
            b2b_client: B2B client instance for fetching product data.
        """
        self.b2b_client = b2b_client or B2BClient()

    async def get_product_card(self, product_id: str) -> ProductCardResponse:
        """
        Fetch product card for B2C.
        
        Steps:
        1. Fetch product from B2B service
        2. Validate visibility (status=MODERATED, deleted=false, blocked=false)
        3. Strip sensitive fields from SKUs
        4. Calculate in_stock for each SKU
        5. Return B2C-safe ProductCardResponse
        
        Args:
            product_id: Product UUID string.
            
        Returns:
            ProductCardResponse with B2C-safe product data.
            
        Raises:
            ProductNotVisibleError: If product is not visible to B2C.
            B2BServiceUnavailableError: If B2B service is down.
            B2BClientError: For other B2B client errors.
        """
        # Step 1: Fetch from B2B
        logger.info(f"Fetching product card for {product_id} from B2B")
        raw_product = await self.b2b_client.get_product_by_id(product_id)

        # Step 2: Validate visibility
        self._validate_visibility(raw_product)

        # Step 3 & 4: Build B2C-safe response
        return self._build_card_response(raw_product)

    def _validate_visibility(self, raw_product: dict) -> None:
        """
        Validate that product is visible to B2C buyers.
        
        Rules:
        - status must be "MODERATED"
        - deleted must be False
        - blocked (is_hard_blocked) must be False
        
        Args:
            raw_product: Raw product dict from B2B.
            
        Raises:
            ProductNotVisibleError: If product is not visible.
        """
        status = raw_product.get("status")
        if status != "MODERATED":
            logger.warning(f"Product not visible: status={status} (expected MODERATED)")
            raise ProductNotVisibleError(
                f"Product is not available (status: {status})"
            )

        deleted = raw_product.get("deleted", False)
        if deleted is True:
            logger.warning("Product not visible: deleted=True")
            raise ProductNotVisibleError("Product is no longer available")

        is_hard_blocked = raw_product.get("is_hard_blocked", False)
        if is_hard_blocked is True:
            logger.warning("Product not visible: is_hard_blocked=True")
            raise ProductNotVisibleError("Product is blocked")

    def _build_card_response(self, raw_product: dict) -> ProductCardResponse:
        """
        Build B2C-safe ProductCardResponse from raw B2B data.
        
        - Strips cost_price and reserved_quantity from SKUs
        - Calculates in_stock = active_quantity > 0
        
        Args:
            raw_product: Raw product dict from B2B.
            
        Returns:
            ProductCardResponse safe for B2C consumption.
        """
        # Build images
        images = [
            ProductImageResponse(
                url=img.get("url", ""),
                ordering=img.get("ordering", 0),
            )
            for img in raw_product.get("images", [])
        ]

        # Build product-level characteristics
        characteristics = [
            CharacteristicResponse(
                name=char.get("name", ""),
                value=char.get("value", ""),
            )
            for char in raw_product.get("characteristics", [])
        ]

        # Build category if present
        category_raw = raw_product.get("category")
        category = None
        if category_raw:
            category = CategoryResponse(
                id=category_raw.get("id"),
                name=category_raw.get("name", ""),
            )

        # Build SKUs (stripping sensitive fields)
        skus = []
        for raw_sku in raw_product.get("skus", []):
            sku = self._build_sku_card(raw_sku)
            skus.append(sku)

        return ProductCardResponse(
            id=raw_product.get("id"),
            slug=raw_product.get("slug"),
            title=raw_product.get("title", ""),
            description=raw_product.get("description"),
            status=raw_product.get("status", ""),
            category=category,
            images=images,
            characteristics=characteristics,
            skus=skus,
        )

    def _build_sku_card(self, raw_sku: dict) -> SKUCardResponse:
        """
        Build B2C-safe SKUCardResponse from raw SKU data.
        
        IMPORTANT: Explicitly does NOT include cost_price or reserved_quantity.
        
        Args:
            raw_sku: Raw SKU dict from B2B.
            
        Returns:
            SKUCardResponse without sensitive fields.
        """
        # SECURITY: Explicitly exclude sensitive fields
        # cost_price is NEVER included
        # reserved_quantity is NEVER included
        
        active_quantity = raw_sku.get("active_quantity", 0)
        in_stock = active_quantity > 0

        # Build SKU characteristics
        sku_characteristics = [
            CharacteristicResponse(
                name=char.get("name", ""),
                value=char.get("value", ""),
            )
            for char in raw_sku.get("characteristics", [])
        ]

        return SKUCardResponse(
            id=raw_sku.get("id"),
            name=raw_sku.get("name", ""),
            price=raw_sku.get("price", 0),
            discount=raw_sku.get("discount", 0),
            image=raw_sku.get("image"),
            in_stock=in_stock,
            active_quantity=active_quantity,
            characteristics=sku_characteristics,
        )