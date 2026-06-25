"""
B2C Cart API Router.

Provides endpoints for cart management including:
- Get enriched cart
- Add/update/remove items
- Clear cart

Authentication:
- Authenticated users: Bearer JWT (user_id extracted from token)
- Guest users: X-Session-Id header

IDOR Protection:
- user_id comes from JWT, NEVER from body
- session_id comes from header, NEVER from body
- Carts are only accessible by their owner
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_async_session
from models.cart_models import Cart, CartItem
from schemas.cart_schemas import (
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartResponse,
)
from services.cart_service import CartService


router = APIRouter(
    tags=["B2C - Cart"],
)


async def get_current_user_id(
    authorization: Optional[str] = Header(None),
) -> Optional[uuid.UUID]:
    """
    Extract user_id from Bearer JWT token.

    In production, this would validate the JWT signature.
    For now, expects format: "Bearer <uuid>"

    Args:
        authorization: Authorization header value.

    Returns:
        user UUID if authenticated, None if guest.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()
        try:
            return uuid.UUID(token)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
            )
    return None


async def get_session_id(
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
) -> Optional[str]:
    """
    Extract session ID from header.

    Args:
        x_session_id: X-Session-Id header value.

    Returns:
        Session ID string or None.
    """
    return x_session_id


async def get_cart_owner(
    authorization: Optional[str] = Header(None),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
) -> tuple[Optional[uuid.UUID], Optional[str]]:
    """
    Resolve cart owner from auth headers.

    Returns:
        Tuple of (user_id, session_id).
        At least one must be present.
    """
    user_id = await get_current_user_id(authorization)
    session_id = await get_session_id(x_session_id)

    if user_id is None and session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer token or X-Session-Id header.",
        )

    return user_id, session_id


@router.get(
    "/cart",
    response_model=CartResponse,
    summary="Get current cart",
    description="Retrieve the current user's or session's cart with enriched B2B data.",
    responses={
        200: {"description": "Cart retrieved successfully"},
        401: {"description": "Authentication required"},
    },
)
async def get_cart(
    user_id: Optional[uuid.UUID] = Depends(get_current_user_id),
    session_id: Optional[str] = Depends(get_session_id),
    cart_owner=Depends(get_cart_owner),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Get the current cart with enriched data.

    Identifies the user via JWT or session and returns their cart
    with current SKU data from B2B catalog.
    """
    resolved_user_id, resolved_session_id = cart_owner

    # Use user_id if available, otherwise session_id
    owner_user_id = resolved_user_id
    owner_session_id = resolved_session_id if owner_user_id is None else None

    service = CartService(session)
    cart = await service.get_or_create_cart(
        user_id=str(owner_user_id) if owner_user_id else None,
        session_id=owner_session_id,
    )

    return await service.get_enriched_cart(cart)


@router.post(
    "/cart/items",
    response_model=CartResponse,
    summary="Add item to cart",
    description="Add a SKU to the cart or increment quantity if already exists.",
    responses={
        200: {"description": "Item added, returns updated cart"},
        401: {"description": "Authentication required"},
        422: {"description": "Validation error"},
    },
)
async def add_cart_item(
    item: CartItemAddRequest,
    cart_owner=Depends(get_cart_owner),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Add an item to the cart.

    If the SKU already exists in the cart, the quantity is incremented.
    Returns the updated enriched cart.
    """
    resolved_user_id, resolved_session_id = cart_owner

    service = CartService(session)
    cart = await service.get_or_create_cart(
        user_id=str(resolved_user_id) if resolved_user_id else None,
        session_id=resolved_session_id if resolved_user_id is None else None,
    )

    await service.add_item(
        cart=cart,
        sku_id=str(item.sku_id),
        quantity=item.quantity,
    )

    return await service.get_enriched_cart(cart)


@router.put(
    "/cart/items/{sku_id}",
    response_model=CartResponse,
    summary="Update cart item quantity",
    description="Update the quantity of a specific SKU in the cart. Quantity 0 removes the item.",
    responses={
        200: {"description": "Item updated, returns updated cart"},
        401: {"description": "Authentication required"},
        404: {"description": "SKU not found in cart"},
        422: {"description": "Validation error"},
    },
)
async def update_cart_item(
    sku_id: uuid.UUID,
    item: CartItemUpdateRequest,
    cart_owner=Depends(get_cart_owner),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Update a cart item's quantity.

    If quantity is 0, the item is removed from the cart.
    Returns the updated enriched cart.
    """
    resolved_user_id, resolved_session_id = cart_owner

    service = CartService(session)
    cart = await service.get_or_create_cart(
        user_id=str(resolved_user_id) if resolved_user_id else None,
        session_id=resolved_session_id if resolved_user_id is None else None,
    )

    updated_item = await service.update_item(
        cart=cart,
        sku_id=str(sku_id),
        quantity=item.quantity,
    )

    # If item was removed (quantity=0) or didn't exist, still return the cart
    return await service.get_enriched_cart(cart)


@router.delete(
    "/cart/items/{sku_id}",
    response_model=CartResponse,
    summary="Remove item from cart",
    description="Remove a specific SKU from the cart entirely.",
    responses={
        200: {"description": "Item removed, returns updated cart"},
        401: {"description": "Authentication required"},
    },
)
async def remove_cart_item(
    sku_id: uuid.UUID,
    cart_owner=Depends(get_cart_owner),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Remove an item from the cart.

    Completely removes the SKU from the cart regardless of quantity.
    Returns the updated enriched cart.
    """
    resolved_user_id, resolved_session_id = cart_owner

    service = CartService(session)
    cart = await service.get_or_create_cart(
        user_id=str(resolved_user_id) if resolved_user_id else None,
        session_id=resolved_session_id if resolved_user_id is None else None,
    )

    await service.remove_item(cart=cart, sku_id=str(sku_id))

    return await service.get_enriched_cart(cart)


@router.delete(
    "/cart",
    response_model=CartResponse,
    summary="Clear cart",
    description="Remove all items from the cart.",
    responses={
        200: {"description": "Cart cleared"},
        401: {"description": "Authentication required"},
    },
)
async def clear_cart(
    cart_owner=Depends(get_cart_owner),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Clear all items from the cart.

    Removes all items but keeps the cart itself.
    Returns the empty enriched cart.
    """
    resolved_user_id, resolved_session_id = cart_owner

    service = CartService(session)
    cart = await service.get_or_create_cart(
        user_id=str(resolved_user_id) if resolved_user_id else None,
        session_id=resolved_session_id if resolved_user_id is None else None,
    )

    # Use bulk delete to avoid lazy loading issues in async context
    await service.clear_cart(cart)

    return await service.get_enriched_cart(cart)


@router.post(
    "/cart/merge",
    response_model=CartResponse,
    summary="Merge guest cart into user cart",
    description=(
        "Merges the guest cart (from X-Session-Id) into the authenticated user's cart. "
        "For duplicate SKUs, the maximum quantity is kept. "
        "The guest cart is deleted after merge."
    ),
    responses={
        200: {"description": "Carts merged successfully"},
        401: {"description": "Authentication required"},
    },
)
async def merge_cart(
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    authorization: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_async_session),
) -> CartResponse:
    """
    Merge guest cart into authenticated user cart.

    This endpoint is called when a guest user logs in.
    The guest cart items are merged into the user's cart.
    """
    # Extract user_id from JWT
    user_id = await get_current_user_id(authorization)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required for cart merge",
        )

    if x_session_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Session-Id header required for cart merge",
        )

    service = CartService(session)

    # Get both carts
    guest_cart = await service.get_or_create_cart(
        user_id=None,
        session_id=x_session_id,
    )
    auth_cart = await service.get_or_create_cart(
        user_id=str(user_id),
        session_id=None,
    )

    # Merge and return enriched auth cart
    return await service.merge_carts(guest_cart=guest_cart, auth_cart=auth_cart)