"""
Schemas for moderation event processing (webhooks from B2B).
Handles moderation decisions (MODERATED/BLOCKED) sent to the moderation service.
"""

import uuid
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator


class FieldReport(BaseModel):
    """
    Field report for moderation issues.
    
    Represents a specific validation issue found during moderation.
    """
    
    field_name: str = Field(
        ...,
        description="Name of the field with the issue (e.g., 'name', 'price', 'image_url')"
    )
    sku_id: Optional[str] = Field(
        None,
        description="SKU UUID if the issue is specific to a SKU"
    )
    comment: str = Field(
        ...,
        description="Description of the validation issue"
    )


class BlockingReason(BaseModel):
    """
    Reason for product blocking.
    
    Contains the blocking reason details with ID, title, and comment.
    """
    
    id: str = Field(
        ...,
        description="Blocking reason identifier"
    )
    title: str = Field(
        ...,
        description="Short title for the blocking reason"
    )
    comment: str = Field(
        ...,
        description="Detailed explanation for the blocking"
    )


class ModerationEventRequest(BaseModel):
    """
    Request model for moderation decisions sent from B2B.
    
    This webhook receives moderation results (MODERATED or BLOCKED)
    and updates the product status accordingly.
    
    Business rules:
    - HARD_BLOCKED is terminal: PUT/DELETE from seller returns 403
    - field_reports are only saved for soft blocks
    - blocking_reason is mandatory for both BLOCKED and HARD_BLOCKED
    """
    
    idempotency_key: uuid.UUID = Field(
        ...,
        description="Unique key for idempotency (prevents duplicate processing)"
    )
    product_id: uuid.UUID = Field(
        ...,
        description="Product UUID"
    )
    status: str = Field(
        ...,
        description="Moderation decision: MODERATED or BLOCKED",
        pattern="^(MODERATED|BLOCKED)$"
    )
    hard_block: bool = Field(
        False,
        description="Whether this is a hard block (permanent, cannot be edited)"
    )
    blocking_reason: Optional[BlockingReason] = Field(
        None,
        description="Required if status is BLOCKED (soft or hard)"
    )
    field_reports: Optional[List[FieldReport]] = Field(
        None,
        description="Required for soft BLOCKED only (validation issues)"
    )

    @model_validator(mode="after")
    def validate_blocked_requires_reason(self) -> "ModerationEventRequest":
        """
        Validate that BLOCKED status has required blocking_reason.
        
        Rules:
        - blocking_reason is mandatory for both soft and hard blocks
        - field_reports only required for soft blocks (hard blocks may have empty reports)
        
        Raises:
            ValueError: If status is BLOCKED but blocking_reason is missing.
        """
        if self.status == "BLOCKED":
            if self.blocking_reason is None:
                raise ValueError(
                    "blocking_reason is required when status is BLOCKED"
                )
            # field_reports required only for soft blocks
            if not self.hard_block:
                if self.field_reports is None or len(self.field_reports) == 0:
                    raise ValueError(
                        "field_reports is required when status is BLOCKED (soft block)"
                    )
        return self

    class Config:
        json_schema_extra = {
            "examples": {
                "soft_blocked": {
                    "summary": "Soft block with field reports",
                    "value": {
                        "idempotency_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                        "product_id": "12345678-1234-5678-1234-567812345678",
                        "status": "BLOCKED",
                        "hard_block": False,
                        "blocking_reason": {
                            "id": "reason_001",
                            "title": "Incomplete product information",
                            "comment": "Product description is too short"
                        },
                        "field_reports": [
                            {
                                "field_name": "description",
                                "sku_id": None,
                                "comment": "Description must be at least 50 characters"
                            }
                        ]
                    }
                },
                "hard_blocked": {
                    "summary": "Hard block (permanent)",
                    "value": {
                        "idempotency_key": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
                        "product_id": "23456789-2345-6789-2345-678901234567",
                        "status": "BLOCKED",
                        "hard_block": True,
                        "blocking_reason": {
                            "id": "reason_002",
                            "title": "Counterfeit product",
                            "comment": "Product is counterfeit and violates IP rights"
                        },
                        "field_reports": []
                    }
                }
            }
        }


class ModerationEventResponse(BaseModel):
    """
    Response for moderation event processing.
    
    Returns confirmation that the event was processed successfully.
    """
    
    ok: bool = Field(
        ...,
        description="Whether the moderation event was processed successfully"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "ok": True
            }
        }