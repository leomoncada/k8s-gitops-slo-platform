from datetime import datetime

import pytest
from fastapi.testclient import TestClient

ORDER = {
    "customer_id": "cust-42",
    "items": [{"sku": "SKU-1", "qty": 2}, {"sku": "SKU-2", "qty": 1}],
    "note": "leave at the door",
}


def create(client: TestClient, **overrides: object) -> dict:
    response = client.post("/orders", json={**ORDER, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_returns_the_serialized_order(client: TestClient) -> None:
    body = create(client)

    assert isinstance(body["id"], int)
    assert body["customer_id"] == ORDER["customer_id"]
    assert body["items"] == ORDER["items"]
    assert body["note"] == ORDER["note"]
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None


def test_get_returns_the_same_order(client: TestClient) -> None:
    created = create(client)

    response = client.get(f"/orders/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_order_is_404(client: TestClient) -> None:
    response = client.get("/orders/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "order not found"}


def test_null_note_round_trips(client: TestClient) -> None:
    created = create(client, note=None)
    omitted = client.post("/orders", json={k: v for k, v in ORDER.items() if k != "note"})

    assert created["note"] is None
    assert omitted.status_code == 201
    assert omitted.json()["note"] is None
    assert client.get(f"/orders/{created['id']}").json()["note"] is None
    assert [o["note"] for o in client.get("/orders").json()] == [None, None]


def test_list_returns_most_recent_first_with_default_limit(client: TestClient) -> None:
    ids = [create(client, customer_id=f"cust-{i}")["id"] for i in range(25)]

    default = client.get("/orders")
    limited = client.get("/orders", params={"limit": 3})

    assert default.status_code == 200
    assert [o["id"] for o in default.json()] == ids[::-1][:20]
    assert [o["id"] for o in limited.json()] == ids[::-1][:3]


def test_list_accepts_the_maximum_limit(client: TestClient) -> None:
    create(client)

    assert client.get("/orders", params={"limit": 100}).status_code == 200


@pytest.mark.parametrize("limit", [0, -1, 101, "many"])
def test_list_rejects_out_of_range_limits(client: TestClient, limit: object) -> None:
    assert client.get("/orders", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({**ORDER, "customer_id": ""}, id="empty-customer"),
        pytest.param({**ORDER, "items": []}, id="no-items"),
        pytest.param({**ORDER, "items": [{"sku": "A", "qty": 0}]}, id="zero-qty"),
        pytest.param({**ORDER, "items": [{"sku": "A", "qty": -3}]}, id="negative-qty"),
        pytest.param({**ORDER, "items": [{"sku": "A"}]}, id="missing-qty"),
        pytest.param({**ORDER, "items": [{"qty": 1}]}, id="missing-sku"),
        pytest.param({**ORDER, "note": 5}, id="non-string-note"),
        pytest.param({**ORDER, "unexpected": True}, id="unknown-field"),
    ],
)
def test_invalid_orders_are_422(client: TestClient, body: dict) -> None:
    assert client.post("/orders", json=body).status_code == 422


def test_non_integer_id_is_422(client: TestClient) -> None:
    assert client.get("/orders/abc").status_code == 422
