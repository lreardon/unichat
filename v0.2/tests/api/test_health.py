import pytest


@pytest.mark.integration
def test_health_endpoint_returns_ok(client) -> None:
    """Requires running Postgres. Run with: pytest -m integration"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
