from datetime import UTC, datetime

from orders.serialization import serialize_order

ROW = {
    "id": 7,
    "customer_id": "cust-1",
    "items": [{"sku": "SKU-1", "qty": 3}],
    "note": "ring twice",
    "created_at": datetime(2026, 10, 3, 12, 30, tzinfo=UTC),
}


def test_serializes_every_column() -> None:
    assert serialize_order(ROW) == {
        "id": 7,
        "customer_id": "cust-1",
        "items": [{"sku": "SKU-1", "qty": 3}],
        "note": "ring twice",
        "created_at": "2026-10-03T12:30:00+00:00",
    }


def test_null_note_stays_null() -> None:
    assert serialize_order({**ROW, "note": None})["note"] is None
