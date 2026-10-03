"""HTTP routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from psycopg_pool import AsyncConnectionPool

from orders import db
from orders.models import OrderCreate
from orders.serialization import serialize_order

router = APIRouter()


def get_pool(request: Request) -> AsyncConnectionPool:
    return request.app.state.pool


Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: OrderCreate, pool: Pool) -> dict[str, Any]:
    row = await db.insert_order(
        pool,
        customer_id=order.customer_id,
        items=[item.model_dump() for item in order.items],
        note=order.note,
    )
    return serialize_order(row)


@router.get("/orders/{id}")
async def get_order(id: int, pool: Pool) -> dict[str, Any]:  # noqa: A002 - matches the path
    row = await db.get_order(pool, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    return serialize_order(row)


@router.get("/orders")
async def list_orders(
    pool: Pool, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[dict[str, Any]]:
    return [serialize_order(row) for row in await db.list_orders(pool, limit)]


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process answers."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz() -> dict[str, str]:
    """Readiness: the process can serve. Deliberately does not check Postgres.

    If it did, a slow or unreachable database would mark every replica unready
    at once and turn a partial degradation into a full outage (see ADR 2).
    """
    return {"status": "ready"}
