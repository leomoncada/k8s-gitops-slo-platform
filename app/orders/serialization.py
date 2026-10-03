"""The JSON shape of an order. Every order endpoint goes through here."""

from collections.abc import Mapping
from typing import Any


def serialize_order(row: Mapping[str, Any]) -> dict[str, Any]:
    """Turn an ``orders`` row into the response body. ``note`` may be null."""
    return {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "items": row["items"],
        "note": row["note"],
        "created_at": row["created_at"].isoformat(),
    }
