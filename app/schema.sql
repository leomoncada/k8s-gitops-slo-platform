-- Schema for the orders service. Applied by an initContainer (psql)
-- and by the test suite; the service itself never creates schema.
-- Idempotent, so it can safely run on every pod start.

CREATE TABLE IF NOT EXISTS orders (
    id          bigserial   PRIMARY KEY,
    customer_id text        NOT NULL,
    items       jsonb       NOT NULL,
    note        text        NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
