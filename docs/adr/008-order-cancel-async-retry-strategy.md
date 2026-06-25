# ADR-008: Order Cancellation Async Retry Strategy

## Status

Proposed

## Context

When a user cancels an order, the system must call B2B `POST /api/v1/unreserve` to release reserved stock. If the B2B service is unavailable (timeout, 500, 503), the order transitions to `CANCEL_PENDING` status and the unreserve operation must be retried asynchronously.

We need a mechanism to retry failed unreserve operations for orders in `CANCEL_PENDING` status.

## Decision

For the first iteration (MVP/scaffold), we will:
1. Log the failure with order ID and error details
2. Set `cancel_pending_since` timestamp on the order
3. Add a TODO comment for future Celery integration

For production, we will implement **Celery with exponential backoff** as the retry mechanism.

## Alternatives Considered

### 1. Celery with Exponential Backoff (Chosen for production)

**Pros:**
- Battle-tested for async task processing in Python
- Built-in retry with exponential backoff
- Easy to monitor via Flower or similar tools
- Scalable - can add more workers as needed
- Supports task priorities and queues

**Cons:**
- Additional infrastructure dependency (broker like Redis/RabbitMQ)
- More complex setup than simple management commands
- Learning curve for team unfamiliar with Celery

### 2. Management Command with Cron

**Pros:**
- Simple to implement (just a Django/flask command)
- No additional infrastructure needed
- Easy to understand and debug

**Cons:**
- Fixed interval retry (no exponential backoff)
- No built-in dead letter queue
- Harder to monitor task execution
- Risk of overlapping runs if previous run takes longer than interval
- Limited scalability

### 3. Django Q (if using Django)

**Pros:**
- Simpler than Celery
- Built into Django ecosystem
- Uses Django ORM as broker

**Cons:**
- Less mature than Celery
- Smaller community
- Not suitable if not using Django
- Limited monitoring capabilities

## Criteria Evaluation

| Criteria                  | Cron + Command | Django Q | Celery   |
|---------------------------|----------------|----------|----------|
| Setup complexity          | Low            | Medium   | Medium   |
| Execution guarantee       | Medium         | High     | High     |
| Monitoring ease           | Low            | Medium   | High     |
| Scalability               | Low            | Medium   | High     |
| Exponential backoff       | Manual         | Built-in | Built-in |
| Community support         | N/A            | Small    | Large    |

## Decision Rationale

**First iteration (scaffold):**
- Log + status `CANCEL_PENDING` with `cancel_pending_since` timestamp
- No actual retry infrastructure yet
- TODO markers for future implementation

**Production (future iteration):**
- Implement Celery task with exponential backoff (e.g., 1min, 2min, 4min, 8min, 16min, max 30min)
- Max retries: 5-7 before moving to dead letter queue
- Monitor via Flower dashboard
- Alert if `cancel_pending_since` > 30 minutes (stuck order)

## Implementation Sketch (Future)

```python
# tasks.py
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,  # 1 minute
    backoff=True,
    backoff_max=1800,  # 30 minutes max
)
def retry_unreserve(self, order_id: str):
    """Retry unreserve for a CANCEL_PENDING order."""
    from services.cancel_service import CancelService
    try:
        CancelService.attempt_unreserve(order_id)
    except B2BServiceUnavailableError as exc:
        logger.warning(f"Unreserve retry {self.request.retries} failed for order {order_id}: {exc}")
        raise self.retry(exc=exc)
    except B2BClientError as exc:
        # Non-retryable error - log and alert
        logger.error(f"Non-retryable B2B error for order {order_id}: {exc}")
        # Move to CANCEL_FAILED status or alert team
```

## References

- [ADR-006: Cart Identity Strategy](006-cart-identity-strategy.md)
- [Flow: B2C Orders](../flows/b2c-orders-flows.md#b2c-11-cancel-order)