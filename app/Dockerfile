# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.14.8-slim-trixie@sha256:89fb7d3da20043c370643435258bdd7ab755d326d359001d02988ed15ae5219e

# --- build: resolve dependencies into a venv that has no pip of its own ----
FROM ${PYTHON_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv --without-pip /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN pip --python /opt/venv/bin/python install --only-binary=:all: -r /tmp/requirements.txt

COPY orders/ /srv/orders/
RUN python -m compileall -q --invalidation-mode checked-hash /srv/orders

# --- runtime ---------------------------------------------------------------
FROM ${PYTHON_IMAGE}

ARG APP_VERSION=1.0.0
LABEL org.opencontainers.image.title="orders" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV APP_VERSION=${APP_VERSION} \
    PATH=/opt/venv/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 orders \
 && useradd --uid 10001 --gid orders --no-create-home --shell /usr/sbin/nologin orders

COPY --from=build /opt/venv /opt/venv
COPY --from=build /srv/orders /srv/orders
WORKDIR /srv

USER 10001:10001
EXPOSE 8000

# Access logs come from the app (one JSON line per request), not uvicorn.
CMD ["uvicorn", "orders.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
