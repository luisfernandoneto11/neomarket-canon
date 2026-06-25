"""
B2B Client for NeoMarket.

Handles communication with the B2B service for product and SKU data.
Uses async HTTP calls with retry logic and timeout handling.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)


class B2BClientError(Exception):
    """Base exception for B2B client errors."""
    pass


class B2BServiceUnavailableError(B2BClientError):
    """Raised when B2B service is unreachable or returns 503."""
    pass


class B2BClient:
    """
    Client for fetching product data from the B2B service.

    Uses async HTTP calls with retry logic for reliability.
    All requests are authenticated via X-Service-Key header.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        service_key: str = "b2b-service-secret-key",
        timeout: float = 5.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        """
        Initialize B2B client.

        Args:
            base_url: Base URL of the B2B service.
            service_key: Service authentication key for X-Service-Key header.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            retry_delay: Base delay between retries (exponential backoff applied).
        """
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _get_headers(self) -> Dict[str, str]:
        """Build standard headers for B2B requests."""
        return {
            "Content-Type": "application/json",
            "X-Service-Key": self.service_key,
        }

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to B2B with retry logic.

        Uses exponential backoff for transient server errors (502, 503, 504).
        Client errors (4xx) are raised immediately without retry.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: URL path relative to base_url.
            params: Optional query parameters.
            json_data: Optional JSON body.

        Returns:
            Parsed JSON response as dict.

        Raises:
            B2BServiceUnavailableError: If service is down or all retries fail.
            B2BClientError: For client errors (4xx) or unexpected failures.
        """
        url = f"{self.base_url}{path}"
        headers = self._get_headers()
        last_exception: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"B2B request {method} {url} (attempt {attempt}/{self.max_retries})")

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_data,
                        headers=headers,
                    )

                if response.status_code == 200 or response.status_code == 201:
                    return response.json()

                if response.status_code in (400, 401, 403, 404, 409, 422):
                    # Client error - don't retry
                    error_msg = f"B2B client error {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    raise B2BClientError(error_msg)

                # Server error (500, 502, 503, 504) - retry
                logger.warning(
                    f"B2B server error {response.status_code} on attempt {attempt}: {response.text}"
                )
                last_exception = B2BServiceUnavailableError(
                    f"B2B server error: {response.status_code}"
                )

            except httpx.TimeoutException as e:
                logger.warning(
                    f"B2B timeout on attempt {attempt}/{self.max_retries}: {e}"
                )
                last_exception = e

            except httpx.ConnectError as e:
                logger.warning(
                    f"B2B connection error on attempt {attempt}/{self.max_retries}: {e}"
                )
                last_exception = B2BServiceUnavailableError(
                    f"B2B service unreachable: {e}"
                )

            except httpx.RequestError as e:
                logger.warning(
                    f"B2B request error on attempt {attempt}/{self.max_retries}: {e}"
                )
                last_exception = e

            # Wait before retry (except on last attempt)
            if attempt < self.max_retries:
                delay = self.retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                logger.info(f"Retrying B2B request in {delay:.1f}s...")
                await asyncio.sleep(delay)

        # All retries exhausted
        error_msg = f"B2B request failed after {self.max_retries} attempts: {last_exception}"
        logger.error(error_msg)
        raise B2BServiceUnavailableError(error_msg)

    async def get_products(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch product list from B2B with optional filters.

        Calls B2B `GET /api/v1/products` with filter parameters.
        The B2B service handles filtering, sorting, and pagination.

        Args:
            filters: Optional dict of filter parameters:
                - limit: int (1-100)
                - offset: int
                - category: str
                - min_price: float
                - max_price: float
                - in_stock: bool
                - search: str
                - sort: str (price_asc, price_desc, date_asc, date_desc, popularity)

        Returns:
            Dict with product list response:
                - items: list of product dicts with SKUs
                - total: int
                - limit: int
                - offset: int

        Raises:
            B2BServiceUnavailableError: If B2B service is down.
            B2BClientError: For invalid requests.
        """
        # Build query params, filtering out None values
        params = {}
        if filters:
            for key, value in filters.items():
                if value is not None:
                    params[key] = value

        response = await self._request_with_retry(
            method="GET",
            path="/api/v1/products",
            params=params if params else None,
        )

        return response

    async def get_product_by_id(self, product_id: str) -> Dict[str, Any]:
        """
        Fetch a single product by ID from B2B.

        Calls B2B `GET /api/v1/products/{product_id}`.

        Args:
            product_id: Product UUID string.

        Returns:
            Dict with product data including SKUs, blocking_reason, field_reports.

        Raises:
            B2BServiceUnavailableError: If B2B service is down.
            B2BClientError: If product not found (404).
        """
        response = await self._request_with_retry(
            method="GET",
            path=f"/api/v1/products/{product_id}",
        )

        return response

    async def get_products_batch(self, product_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch multiple products by IDs from B2B.

        Makes parallel requests for efficiency.

        Args:
            product_ids: List of product UUID strings.

        Returns:
            List of product data dicts.

        Raises:
            B2BServiceUnavailableError: If B2B service is down.
        """
        tasks = [self.get_product_by_id(pid) for pid in product_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        products = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch product in batch: {result}")
                continue
            products.append(result)

        return products

    async def reserve(self, request) -> Dict[str, Any]:
        """
        Reserve stock for items (all-or-nothing).

        Calls B2B `POST /api/v1/reserve` to reserve stock for all items.
        If any item fails to reserve, the entire reservation fails.

        Args:
            request: ReserveRequest with idempotency_key and items.

        Returns:
            Dict with reservation result.

        Raises:
            B2BClientError: If reservation fails (409 Conflict).
            B2BServiceUnavailableError: If B2B service is down.
        """
        response = await self._request_with_retry(
            method="POST",
            path="/api/v1/reserve",
            json_data=request.model_dump(mode="json"),
        )

        return response

    async def unreserve(self, request) -> Dict[str, Any]:
        """
        Unreserve stock for items (release reservation).

        Calls B2B `POST /api/v1/unreserve` to release reserved stock for items.
        Used when cancelling an order to return stock to available inventory.

        Args:
            request: UnreserveRequest with order_id and items.

        Returns:
            Dict with unreservation result.

        Raises:
            B2BClientError: If unreservation fails (4xx errors).
            B2BServiceUnavailableError: If B2B service is down.
        """
        response = await self._request_with_retry(
            method="POST",
            path="/api/v1/unreserve",
            json_data=request.model_dump(mode="json"),
        )

        return response
