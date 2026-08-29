from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from main import main_app as app


@pytest.mark.asyncio
async def test_openapi_schema_clean_and_isolated():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()

        # 1. Check securitySchemes: ONLY x-api-key should be present
        components = schema.get("components", {})
        security_schemes = components.get("securitySchemes", {})
        assert "APIKeyHeader" in security_schemes
        api_key_schema = security_schemes["APIKeyHeader"]
        assert api_key_schema.get("name") == "x-api-key"

        # Ensure NO internal service key or extra schemas exist
        assert "X-Internal-Service-Key" not in str(security_schemes)
        assert "internal_service_key" not in str(security_schemes)

        # 2. Check public paths
        paths = schema.get("paths", {})
        assert "/api/v1/devices/" in paths
        assert "/api/v1/device-tasks/" in paths
        assert "/api/v1/device-events/" in paths
        assert "/api/v1/webhooks/" in paths
        assert "/api/v1/gauges/" in paths

        # Ensure removed or internal routes are NOT leaked in schema
        assert "/api/v1/postamats/" not in paths
        assert "/api/v1/accounts/" not in paths
        assert "/api/v1/diagnostics/" not in paths

        for path in paths:
            assert not path.startswith("/api/internal/"), f"Internal route {path} leaked into OpenAPI schema!"
            assert "provisioning" not in path, f"Provisioning route {path} leaked into OpenAPI schema!"
            assert "billing" not in path, f"Billing route {path} leaked into OpenAPI schema!"
            assert "admin" not in path, f"Admin route {path} leaked into OpenAPI schema!"
            assert "postamat" not in path, f"Postamat route {path} leaked into OpenAPI schema!"

        # 3. Check parameters in /api/v1/devices/ GET operation
        devices_get = paths["/api/v1/devices/"]["get"]
        params = devices_get.get("parameters", [])
        param_names = [p.get("name") for p in params]

        # Ensure noisy/internal headers and params are NOT in parameters
        assert "orgId" not in param_names
        assert "X-Org-Id" not in param_names
        assert "X-Role" not in param_names
        assert "X-Role-Id" not in param_names
        assert "jwt-role" not in param_names
        assert "Authorization" not in param_names
        assert "X-Internal-Service-Key" not in param_names
        assert "org_id" not in param_names  # query param org_id should not exist for devices


@pytest.mark.asyncio
async def test_docs_endpoints_status():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Scalar UI at /docs
        resp_scalar = await ac.get("/docs")
        assert resp_scalar.status_code == 200
        assert "@scalar/api-reference" in resp_scalar.text

        # Swagger UI at /swagger and /legacy-docs
        resp_swagger = await ac.get("/swagger")
        assert resp_swagger.status_code == 200
        assert "swagger-ui" in resp_swagger.text

        resp_legacy = await ac.get("/legacy-docs")
        assert resp_legacy.status_code == 200
        assert "swagger-ui" in resp_legacy.text

        # ReDoc at /redoc
        resp_redoc = await ac.get("/redoc")
        assert resp_redoc.status_code == 200
        assert "redoc" in resp_redoc.text
