"""Postgres access: the connection pool and the three queries the API needs.

The app never creates schema; ``schema.sql`` is applied by an initContainer.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from orders.config import Settings


def create_pool(settings: Settings) -> AsyncConnectionPool:
    """Build a pool whose failures surface as errors, never as hangs.

    - ``timeout``: how long a request waits for a free connection (PoolTimeout).
    - ``connect_timeout``: how long one connection attempt may take.
    - ``statement_timeout``: server-side cap on every statement (QueryCanceled).

    The pool is opened without waiting, so the process starts (and stays
    ready) while Postgres is down; the pool keeps reconnecting in the background.
    """
    return AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "connect_timeout": settings.db_connect_timeout,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
            "application_name": settings.service_name,
        },
        name=settings.service_name,
        open=False,
    )


async def insert_order(
    pool: AsyncConnectionPool,
    customer_id: str,
    items: list[dict[str, Any]],
    note: str | None,
) -> dict[str, Any]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO orders (customer_id, items, note) VALUES (%s, %s, %s) "
            "RETURNING id, customer_id, items, note, created_at",
            (customer_id, Jsonb(items), note),
        )
        row = await cur.fetchone()
    if row is None:  # INSERT ... RETURNING always yields a row
        raise RuntimeError("INSERT returned no row")
    return row


async def get_order(pool: AsyncConnectionPool, order_id: int) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, customer_id, items, note, created_at FROM orders WHERE id = %s",
            (order_id,),
        )
        return await cur.fetchone()


async def list_orders(pool: AsyncConnectionPool, limit: int) -> list[dict[str, Any]]:
    # Newest first by primary key rather than created_at: it uses the PK index,
    # so the query stays fast as baseline traffic keeps growing the table.
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, customer_id, items, note, created_at FROM orders ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return await cur.fetchall()
