import pytest

from orders.config import Settings

URL = "postgresql://orders:orders@db:5432/orders"


def test_defaults() -> None:
    settings = Settings.from_env({"DATABASE_URL": URL})

    assert settings.database_url == URL
    assert settings.service_name == "orders"
    assert settings.app_version == "1.0.0"
    assert settings.log_json is True
    assert settings.otlp_traces_endpoint is None
    assert settings.db_pool_timeout == 2.0
    assert settings.db_statement_timeout_ms == 3000


def test_environment_overrides() -> None:
    settings = Settings.from_env(
        {
            "DATABASE_URL": URL,
            "OTEL_SERVICE_NAME": "orders-canary",
            "APP_VERSION": "1.1.0",
            "LOG_JSON": "false",
        }
    )

    assert (settings.service_name, settings.app_version, settings.log_json) == (
        "orders-canary",
        "1.1.0",
        False,
    )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318"}, "http://otel-collector:4318/v1/traces"),
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318/"}, "http://otel-collector:4318/v1/traces"),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://ignored:4318",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://tempo:4318/custom",
            },
            "http://tempo:4318/custom",
        ),
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": ""}, None),
    ],
)  # fmt: skip
def test_otlp_traces_endpoint(env: dict[str, str], expected: str | None) -> None:
    assert Settings.from_env({"DATABASE_URL": URL, **env}).otlp_traces_endpoint == expected


def test_database_url_is_required() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings.from_env({})


def test_invalid_boolean_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a boolean"):
        Settings.from_env({"DATABASE_URL": URL, "LOG_JSON": "maybe"})
