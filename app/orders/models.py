"""Request bodies. Responses are plain dicts built by ``serialize_order``."""

from pydantic import BaseModel, ConfigDict, Field


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0, le=10_000)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=64)
    items: list[OrderItem] = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)
