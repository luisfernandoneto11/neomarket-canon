"""
B2B Service for NeoMarket Moderation.

Handles business logic for SKU creation, including:
- Product validation
- HARD_BLOCKED status check
- First SKU detection
- Event emission to Moderation service
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product, SKU
from schemas.b2b_schemas import SKUCreateRequest, SKUResponse, ModerationEvent, EventPayload
from clients.moderation_client import ModerationClient


class B2BServiceError(Exception):
    """Base exception for B2B service errors."""
    pass


class ProductNotFoundError(B2BServiceError):
    """Raised when product is not found."""
    pass


class ProductHardBlockedError(B2BServiceError):
    """Raised when product is HARD_BLOCKED."""
    pass


class DuplicateSKUCodeError(B2BServiceError):
    """Raised when SKU code already exists."""
    pass


class B2BService:
    """
    Service for B2B product and SKU operations.
    
    Handles business logic for SKU creation including validation,
    first SKU detection, and event emission.
    """
    
    def __init__(self, session: AsyncSession, moderation_client: Optional[ModerationClient] = None):
        """
        Initialize B2B service.
        
        Args:
            session: Database session.
            moderation_client: Client for sending events to Moderation service.
        """
        self.session = session
        self.moderation_client = moderation_client or ModerationClient()
    
    async def get_product(self, product_id: uuid.UUID) -> Optional[Product]:
        """
        Get product by ID.
        
        Args:
            product_id: Product UUID.
            
        Returns:
            Product instance or None if not found.
        """
        query = select(Product).where(Product.id == product_id)
        result = await self.session.execute(query)
        return result.scalars().first()
    
    async def check_product_not_hard_blocked(self, product: Product) -> None:
        """
        Check if product is not HARD_BLOCKED.
        
        Args:
            product: Product to check.
            
        Raises:
            ProductHardBlockedError: If product is HARD_BLOCKED.
        """
        if product.is_hard_blocked:
            raise ProductHardBlockedError(
                f"Product {product.id} is HARD_BLOCKED and cannot be modified"
            )
    
    async def check_sku_code_unique(self, sku_code: str) -> None:
        """
        Check if SKU code is unique.
        
        Args:
            sku_code: SKU code to check.
            
        Raises:
            DuplicateSKUCodeError: If SKU code already exists.
        """
        query = select(SKU).where(SKU.sku_code == sku_code)
        result = await self.session.execute(query)
        existing = result.scalars().first()
        
        if existing:
            raise DuplicateSKUCodeError(
                f"SKU with code '{sku_code}' already exists"
            )
    
    async def count_skus_for_product(self, product_id: uuid.UUID) -> int:
        """
        Count SKUs for a product.
        
        Args:
            product_id: Product UUID.
            
        Returns:
            Number of SKUs for the product.
        """
        query = select(func.count(SKU.id)).where(SKU.product_id == product_id)
        result = await self.session.execute(query)
        return result.scalar() or 0
    
    async def is_first_sku(self, product_id: uuid.UUID) -> bool:
        """
        Check if this would be the first SKU for the product.
        
        Args:
            product_id: Product UUID.
            
        Returns:
            True if this is the first SKU, False otherwise.
        """
        count = await self.count_skus_for_product(product_id)
        return count == 0
    
    async def create_sku(self, sku_data: SKUCreateRequest) -> SKUResponse:
        """
        Create a new SKU for a product.
        
        This method:
        1. Validates product exists
        2. Validates product is not HARD_BLOCKED
        3. Validates SKU code uniqueness
        4. Checks if this is the first SKU
        5. Creates the SKU
        6. Sends event to Moderation if first SKU
        
        Args:
            sku_data: SKU creation request data.
            
        Returns:
            Created SKU response.
            
        Raises:
            ProductNotFoundError: If product not found.
            ProductHardBlockedError: If product is HARD_BLOCKED.
            DuplicateSKUCodeError: If SKU code already exists.
        """
        # Step 1: Get and validate product
        product = await self.get_product(sku_data.product_id)
        if not product:
            raise ProductNotFoundError(
                f"Product with id {sku_data.product_id} not found"
            )
        
        # Step 2: Check product is not HARD_BLOCKED
        await self.check_product_not_hard_blocked(product)
        
        # Step 3: Check SKU code uniqueness
        await self.check_sku_code_unique(sku_data.sku_code)
        
        # Step 4: Check if this is the first SKU
        is_first = await self.is_first_sku(sku_data.product_id)
        
        # Step 5: Create SKU
        new_sku = SKU(
            product_id=sku_data.product_id,
            sku_code=sku_data.sku_code,
            price=sku_data.price,
            image_url=str(sku_data.image_url) if sku_data.image_url else None,
            stock_quantity=sku_data.stock_quantity,
        )
        
        self.session.add(new_sku)
        await self.session.flush()
        await self.session.refresh(new_sku)
        
        # Step 6: Send event to Moderation if first SKU
        if is_first:
            await self._send_first_sku_event(new_sku, product)
        
        return SKUResponse.model_validate(new_sku)
    
    async def _send_first_sku_event(self, sku: SKU, product: Product) -> None:
        """
        Send event to Moderation service when first SKU is created.
        
        This triggers the moderation workflow for the product.
        
        Args:
            sku: Created SKU.
            product: Parent product.
        """
        # Generate idempotency key for the event
        idempotency_key = uuid.uuid4()
        
        # Build event payload
        payload = EventPayload(
            json_after={
                "sku_id": str(sku.id),
                "sku_code": sku.sku_code,
                "product_id": str(product.id),
                "product_name": product.name,
                "price": float(sku.price),
                "image_url": sku.image_url,
                "stock_quantity": sku.stock_quantity,
                "event": "FIRST_SKU_CREATED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        
        # Build moderation event
        event = ModerationEvent(
            event_type="FIRST_SKU_CREATED",
            idempotency_key=idempotency_key,
            occurred_at=datetime.now(timezone.utc),
            payload=payload,
        )
        
        # Send event to Moderation service
        await self.moderation_client.send_event(event)