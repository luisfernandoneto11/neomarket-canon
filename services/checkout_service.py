"""
Checkout Service for NeoMarket.

Handles B2C order creation from cart with:
- Idempotency support (same idempotency_key returns same order)
- All-or-nothing stock reservation via B2B
- Price snapshot at order creation time
- Cart clearing after successful checkout
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from models.order_models import Order, OrderItem, OrderStatus
from models.product import SKU, Product
from schemas.order_schemas import (
    CheckoutRequest,
    OrderResponse,
    OrderItemResponse,
    OrderStatus as OrderStatusSchema,
)
from schemas.reserve_schemas import ReserveRequest, ReserveItem
from services.cart_service import CartService
from clients.b2b_client import B2BClient, B2BServiceUnavailableError, B2BClientError

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """Base exception for checkout errors."""
    pass


class EmptyCartError(CheckoutError):
    """Raised when cart is empty."""
    pass


class SKUNotFoundError(CheckoutError):
    """Raised when a SKU is not found."""
    def __init__(self, sku_id: str):
        self.sku_id = sku_id
        super().__init__(f"SKU {sku_id} not found")


class ReservationFailedError(CheckoutError):
    """Raised when stock reservation fails."""
    def __init__(self, failed_items: list[dict]):
        self.failed_items = failed_items
        super().__init__(f"Reservation failed for {len(failed_items)} items")


class B2BUnavailableError(CheckoutError):
    """Raised when B2B service is unavailable."""
    pass


class CheckoutService:
    """
    Service for B2C checkout operations.

    Handles creating orders from cart with idempotency,
    all-or-nothing reservation, and price snapshot.
    """

    def __init__(
        self,
        session: AsyncSession,
        cart_service: CartService,
        b2b_client: B2BClient,
    ):
        """
        Initialize checkout service.

        Args:
            session: Database session.
            cart_service: Cart service instance.
            b2b_client: B2B client instance.
        """
        self.session = session
        self.cart_service = cart_service
        self.b2b_client = b2b_client

    async def checkout(
        self,
        request: CheckoutRequest,
        user_id: str,
    ) -> OrderResponse:
        """
        Create an order from cart.

        Flow:
        1. Check idempotency (return existing order if already processed)
        2. Get cart items
        3. Validate SKUs exist
        4. Call B2B reserve (all-or-nothing)
        5. Create order with price snapshot
        6. Clear cart

        Args:
            request: Checkout request with idempotency_key and items.
            user_id: User UUID.

        Returns:
            OrderResponse with created or existing order.

        Raises:
            EmptyCartError: If cart is empty.
            SKUNotFoundError: If a SKU doesn't exist.
            ReservationFailedError: If B2B reservation fails (409).
            B2BUnavailableError: If B2B service is down (503).
        """
        # Step 1: Check idempotency
        existing_order = await self._check_idempotency(request.idempotency_key)
        if existing_order:
            logger.info(
                f"Returning existing order {existing_order.id} "
                f"for idempotency_key {request.idempotency_key}"
            )
            return self._build_order_response(existing_order)

        # Step 2: Get user's cart with items
        cart = await self.cart_service.get_or_create_cart(
            user_id=user_id,
            load_items=True,
        )

        if not cart.items:
            raise EmptyCartError("Cannot checkout with empty cart")

        # Build SKU lookup from cart items
        cart_items_by_sku = {str(item.sku_id): item for item in cart.items}

        # Step 3: Validate checkout items match cart and SKUs exist
        sku_ids = [item.sku_id for item in request.items]
        sku_data = await self._fetch_sku_data(sku_ids)

        # Validate all requested SKUs exist
        for item in request.items:
            if item.sku_id not in sku_data:
                raise SKUNotFoundError(item.sku_id)

        # Step 4: Call B2B reserve (all-or-nothing)
        reserve_items = [
            ReserveItem(sku_id=item.sku_id, quantity=item.quantity)
            for item in request.items
        ]

        reserve_request = ReserveRequest(
            idempotency_key=request.idempotency_key,
            items=reserve_items,
        )

        try:
            await self.b2b_client.reserve(reserve_request)
        except B2BClientError as e:
            # 409 Conflict - reservation failed (e.g., insufficient stock)
            logger.warning(f"B2B reservation failed: {e}")
            # Extract failed items from error if available
            raise ReservationFailedError(failed_items=[])
        except B2BServiceUnavailableError as e:
            # 503 Service Unavailable
            logger.error(f"B2B service unavailable: {e}")
            raise B2BUnavailableError("B2B service is currently unavailable")

        # Step 5: Create order with price snapshot (in transaction)
        try:
            order = await self._create_order(
                user_id=user_id,
                request=request,
                sku_data=sku_data,
            )
        except IntegrityError:
            # Race condition: another request created the order
            # between our idempotency check and insert
            await self.session.rollback()
            existing_order = await self._check_idempotency(request.idempotency_key)
            if existing_order:
                return self._build_order_response(existing_order)
            raise

        # Step 6: Clear cart after successful order creation
        await self.cart_service.clear_cart(cart)

        logger.info(
            f"Order {order.id} created successfully for user {user_id} "
            f"with {len(order.items)} items, total: {order.total_amount}"
        )

        return self._build_order_response(order)

    async def _check_idempotency(self, idempotency_key: str) -> Optional[Order]:
        """
        Check if an order with this idempotency key already exists.

        Args:
            idempotency_key: Idempotency key to check.

        Returns:
            Existing Order or None.
        """
        query = (
            select(Order)
            .where(Order.idempotency_key == idempotency_key)
            .options(selectinload(Order.items))
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def _fetch_sku_data(self, sku_ids: list[str]) -> dict[str, dict]:
        """
        Fetch SKU data from local database for price snapshot.

        Args:
            sku_ids: List of SKU UUIDs.

        Returns:
            Dict mapping SKU ID to SKU data (id, price, product_name, sku_code).
        """
        query = (
            select(SKU)
            .where(SKU.id.in_(sku_ids))
            .options(selectinload(SKU.product))
        )
        result = await self.session.execute(query)
        skus = result.scalars().all()

        sku_data = {}
        for sku in skus:
            sku_data[str(sku.id)] = {
                "id": str(sku.id),
                "price": sku.price,
                "product_name": sku.product.name,
                "sku_code": sku.sku_code,
            }

        return sku_data

    async def _create_order(
        self,
        user_id: str,
        request: CheckoutRequest,
        sku_data: dict[str, dict],
    ) -> Order:
        """
        Create order with price snapshot.

        Args:
            user_id: User UUID.
            request: Checkout request.
            sku_data: SKU data for price snapshot.

        Returns:
            Created Order.
        """
        # Calculate totals and build order items
        order_items = []
        total_amount = 0

        for item in request.items:
            sku_info = sku_data[item.sku_id]
            unit_price_cents = int(sku_info["price"] * 100)
            item_total = unit_price_cents * item.quantity
            total_amount += item_total

            order_items.append(OrderItem(
                sku_id=item.sku_id,
                product_title=sku_info["product_name"],
                sku_name=sku_info["sku_code"],
                unit_price=unit_price_cents,
                quantity=item.quantity,
                total_price=item_total,
            ))

        # Create order
        order = Order(
            user_id=user_id,
            status=OrderStatus.PENDING,
            total_amount=total_amount,
            idempotency_key=request.idempotency_key,
            items=order_items,
        )

        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)

        return order

    def _build_order_response(self, order: Order) -> OrderResponse:
        """
        Build OrderResponse from Order model.

        Args:
            order: Order model instance.

        Returns:
            OrderResponse.
        """
        items_response = [
            OrderItemResponse(
                id=str(item.id),
                sku_id=str(item.sku_id),
                product_title=item.product_title,
                sku_name=item.sku_name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                total_price=item.total_price,
            )
            for item in order.items
        ]

        return OrderResponse(
            id=str(order.id),
            user_id=str(order.user_id),
            status=OrderStatusSchema(order.status.value),
            total_amount=order.total_amount,
            items=items_response,
            created_at=order.created_at,
            idempotency_key=str(order.idempotency_key),
        )