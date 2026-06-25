"""
Moderation Client for NeoMarket.

Handles communication with the Moderation service for sending events.
Uses async HTTP calls with retry logic.
"""

import asyncio
import logging
from typing import Optional

import httpx

from schemas.b2b_schemas import ModerationEvent

logger = logging.getLogger(__name__)


class ModerationClientError(Exception):
    """Base exception for Moderation client errors."""
    pass


class ModerationClient:
    """
    Client for sending events to the Moderation service.
    
    Uses async HTTP calls with retry logic for reliability.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        service_key: str = "b2b-service-key",
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize Moderation client.
        
        Args:
            base_url: Base URL of the Moderation service.
            service_key: Service authentication key.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            retry_delay: Delay between retries in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    async def send_event(self, event: ModerationEvent) -> bool:
        """
        Send event to Moderation service asynchronously.
        
        Uses retry logic for transient failures.
        
        Args:
            event: Moderation event to send.
            
        Returns:
            True if event was sent successfully.
            
        Raises:
            ModerationClientError: If all retry attempts fail.
        """
        url = f"{self.base_url}/api/v1/b2b/events"
        
        headers = {
            "Content-Type": "application/json",
            "X-Service-Key": self.service_key,
            "Idempotency-Key": str(event.idempotency_key),
        }
        
        payload = {
            "event_type": event.event_type,
            "idempotency_key": str(event.idempotency_key),
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload.model_dump(),
        }
        
        last_exception: Optional[Exception] = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"Sending event {event.event_type} to Moderation "
                    f"(attempt {attempt}/{self.max_retries})"
                )
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                    )
                
                if response.status_code == 200:
                    logger.info(
                        f"Event {event.event_type} sent successfully "
                        f"on attempt {attempt}"
                    )
                    return True
                
                if response.status_code in (400, 401, 403, 404, 409):
                    # Client errors - don't retry
                    error_msg = (
                        f"Client error {response.status_code}: {response.text}"
                    )
                    logger.error(error_msg)
                    raise ModerationClientError(error_msg)
                
                # Server error - retry
                logger.warning(
                    f"Server error {response.status_code} on attempt {attempt}. "
                    f"Response: {response.text}"
                )
                last_exception = ModerationClientError(
                    f"Server error: {response.status_code}"
                )
                
            except httpx.TimeoutException as e:
                logger.warning(
                    f"Timeout on attempt {attempt}/{self.max_retries}: {e}"
                )
                last_exception = e
                
            except httpx.RequestError as e:
                logger.warning(
                    f"Request error on attempt {attempt}/{self.max_retries}: {e}"
                )
                last_exception = e
            
            # Wait before retry (except on last attempt)
            if attempt < self.max_retries:
                delay = self.retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                logger.info(f"Retrying in {delay:.1f} seconds...")
                await asyncio.sleep(delay)
        
        # All retries exhausted
        error_msg = (
            f"Failed to send event after {self.max_retries} attempts: "
            f"{last_exception}"
        )
        logger.error(error_msg)
        raise ModerationClientError(error_msg)