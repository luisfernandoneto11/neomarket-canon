"""
Cart Service for NeoMarket.

Handles B2C cart operations including:
- Cart creation/retrieval (user or guest session)
- Adding, updating, removing items
- Cart merging (guest to authenticated user)
- Cart enrichment with current SKU/Product data and availability status.
"""

from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.cart_models import Cart, CartItem
from models.product import Product, SKU
from schemas.cart_schemas import CartItemResponse, CartResponse, UnavailableReason


class CartServiceError(Exception):
    """Base exception for cart service errors."""
    pass


class CartNotFoundError(CartServiceError):
    """Raised when a cart is not found."""
    pass


class CartService:
    """
    Service for B2C cart operations.

    Handles creating carts, managing items, merging guest carts to
    authenticated user carts, and enriching cart data with current
    SKU/Product state for display.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize cart service.

        Args:
            session: Database session.
        """
        self.session = session

    async def get_or_create_cart(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        load_items: bool = False,
    ) -> Cart:
        """
        Get existing cart or create a new one.

        If user_id is provided, looks for user's cart or creates one.
        If only session_id is provided, looks for guest cart or creates one.

        Args:
            user_id: Authenticated user UUID (optional).
            session_id: Guest session identifier (optional).
            load_items: If True, eagerly load cart items.

        Returns:
            Cart instance (existing or new).
        """
        cart: Optional[Cart] = None

        if user_id:
            query = select(Cart).where(Cart.user_id == user_id)
            if load_items:
                query = query.options(selectinload(Cart.items))
            result = await self.session.execute(query)
            cart = result.scalars().first()

        if cart is None and session_id:
            query = select(Cart).where(Cart.session_id == session_id)
            if load_items:
                query = query.options(selectinload(Cart.items))
            result = await self.session.execute(query)
            cart = result.scalars().first()

        if cart is None:
            cart = Cart(
                user_id=user_id,
                session_id=session_id,
            )
            self.session.add(cart)
            await self.session.commit()
            await self.session.refresh(cart)

        return cart

    async def add_item(
        self,
        cart: Cart,
        sku_id: str,
        quantity: int,
    ) -> Optional[CartItem]:
        """
        Add an item to the cart.

        If the SKU already exists in the cart, increment the quantity.
        If resulting quantity is 0 or less, remove the item.

        Args:
            cart: Cart instance.
            sku_id: SKU UUID string to add.
            quantity: Quantity to add (must be > 0 to add new).

        Returns:
            Created or updated CartItem, or None if removed.
        """
        query = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.sku_id == sku_id,
        )
        result = await self.session.execute(query)
        existing_item = result.scalars().first()

        if existing_item:
            existing_item.quantity += quantity
            if existing_item.quantity <= 0:
                await self.session.delete(existing_item)
                await self.session.commit()
                return None
            await self.session.commit()
            await self.session.refresh(existing_item)
            return existing_item
        else:
            if quantity <= 0:
                return None
            new_item = CartItem(
                cart_id=cart.id,
                sku_id=sku_id,
                quantity=quantity,
            )
            self.session.add(new_item)
            await self.session.commit()
            await self.session.refresh(new_item)
            return new_item

    async def update_item(
        self,
        cart: Cart,
        sku_id: str,
        quantity: int,
    ) -> Optional[CartItem]:
        """
        Update the quantity of an item in the cart.

        If quantity > 0, update to that value.
        If quantity = 0, remove the item from cart.

        Args:
            cart: Cart instance.
            sku_id: SKU UUID string to update.
            quantity: New quantity (0 means remove).

        Returns:
            Updated CartItem or None if removed/not found.
        """
        query = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.sku_id == sku_id,
        )
        result = await self.session.execute(query)
        item = result.scalars().first()

        if item is None:
            return None

        if quantity <= 0:
            await self.session.delete(item)
            await self.session.commit()
            return None

        item.quantity = quantity
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def remove_item(
        self,
        cart: Cart,
        sku_id: str,
    ) -> None:
        """
        Remove an item from the cart.

        Args:
            cart: Cart instance.
            sku_id: SKU UUID string to remove.
        """
        query = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.sku_id == sku_id,
        )
        result = await self.session.execute(query)
        item = result.scalars().first()

        if item:
            await self.session.delete(item)
            await self.session.commit()

    async def clear_cart(self, cart: Cart) -> None:
        """
        Remove all items from the cart.

        Uses bulk delete to avoid lazy loading issues in async context.

        Args:
            cart: Cart instance.
        """
        stmt = delete(CartItem).where(CartItem.cart_id == cart.id)
        await self.session.execute(stmt)
        await self.session.commit()

    async def merge_carts(
        self,
        guest_cart: Cart,
        auth_cart: Cart,
    ) -> CartResponse:
        """
        Merge guest cart into authenticated user cart.

        For each item in guest_cart:
        - If SKU exists in auth_cart -> set auth quantity = MAX(auth, guest)
        - If SKU does not exist -> add to auth_cart

        After merge, deletes the guest_cart.

        Args:
            guest_cart: Guest cart to merge from.
            auth_cart: Authenticated user cart to merge into.

        Returns:
            Enriched CartResponse of the merged auth_cart.
        """
        guest_query = (
            select(Cart)
            .where(Cart.id == guest_cart.id)
            .options(selectinload(Cart.items))
        )
        guest_result = await self.session.execute(guest_query)
        guest_cart_loaded = guest_result.scalars().first()

        auth_query = (
            select(Cart)
            .where(Cart.id == auth_cart.id)
            .options(selectinload(Cart.items))
        )
        auth_result = await self.session.execute(auth_query)
        auth_cart_loaded = auth_result.scalars().first()

        auth_items_by_sku = {
            str(item.sku_id): item for item in auth_cart_loaded.items
        }

        for guest_item in guest_cart_loaded.items:
            sku_id_str = str(guest_item.sku_id)
            if sku_id_str in auth_items_by_sku:
                existing = auth_items_by_sku[sku_id_str]
                existing.quantity = max(existing.quantity, guest_item.quantity)
            else:
                new_item = CartItem(
                    cart_id=auth_cart.id,
                    sku_id=guest_item.sku_id,
                    quantity=guest_item.quantity,
                )
                self.session.add(new_item)

        await self.session.delete(guest_cart)
        await self.session.commit()

        await self.session.refresh(auth_cart_loaded)
        return await self.get_enriched_cart(auth_cart_loaded)

    async def get_enriched_cart(self, cart: Cart) -> CartResponse:
        """
        Get cart with enriched item data from B2B catalog.

        For each item in the cart, fetches the current SKU and Product
        data to provide availability status and pricing. Calculates
        unavailable_reason if the item cannot be purchased.

        Args:
            cart: Cart instance.

        Returns:
            CartResponse with enriched items and totals.
        """
        query = (
            select(Cart)
            .where(Cart.id == cart.id)
            .options(selectinload(Cart.items))
        )
        result = await self.session.execute(query)
        cart_with_items = result.scalars().first()

        items_response = []
        total_amount_cents = 0
        total_items = 0

        for cart_item in cart_with_items.items:
            enriched_item = await self._enrich_cart_item(cart_item)
            items_response.append(enriched_item)

            total_items += cart_item.quantity

            if enriched_item.unavailable_reason is None:
                sku_data = enriched_item.sku_data
                if sku_data and "price" in sku_data:
                    total_amount_cents += int(sku_data["price"] * 100) * cart_item.quantity

        return CartResponse(
            items=items_response,
            total_amount=total_amount_cents,
            total_items=total_items,
        )

    async def _enrich_cart_item(
        self, cart_item: CartItem
    ) -> CartItemResponse:
        """
        Enrich a single cart item with current SKU and Product data.

        Never includes cost_price or reserved_quantity in sku_data.

        Args:
            cart_item: CartItem instance.

        Returns:
            CartItemResponse with availability data.
        """
        query = (
            select(SKU)
            .where(SKU.id == cart_item.sku_id)
            .options(selectinload(SKU.product))
        )
        result = await self.session.execute(query)
        sku = result.scalars().first()

        if sku is None:
            return CartItemResponse(
                sku_id=str(cart_item.sku_id),
                sku_data=None,
                quantity=cart_item.quantity,
                unavailable_reason=UnavailableReason.SKU_NOT_FOUND,
            )

        product = sku.product

        unavailable_reason = self._determine_unavailable_reason(sku, product)

        sku_data = {
            "id": str(sku.id),
            "sku_code": sku.sku_code,
            "price": float(sku.price),
            "image_url": sku.image_url,
            "active_quantity": sku.active_quantity,
            "product_id": str(product.id),
            "product_name": product.name,
            "product_status": product.status,
        }

        return CartItemResponse(
            sku_id=str(cart_item.sku_id),
            sku_data=sku_data,
            quantity=cart_item.quantity,
            unavailable_reason=unavailable_reason,
        )

    def _determine_unavailable_reason(
        self, sku: SKU, product: Product
    ) -> Optional[UnavailableReason]:
        """
        Determine why a cart item is unavailable.

        Checks (in priority order):
        1. SKU does not exist (handled in _enrich_cart_item)
        2. Product is deleted -> PRODUCT_DELETED
        3. Product status is not MODERATED -> PRODUCT_BLOCKED
        4. SKU active_quantity == 0 -> OUT_OF_STOCK

        Args:
            sku: SKU instance.
            product: Parent Product instance.

        Returns:
            UnavailableReason or None if available.
        """
        if product.deleted:
            return UnavailableReason.PRODUCT_DELETED

        if not product.is_moderated:
            return UnavailableReason.PRODUCT_BLOCKED

        if sku.active_quantity == 0:
            return UnavailableReason.OUT_OF_STOCK

        return None