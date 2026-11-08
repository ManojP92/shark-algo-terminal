"""
test_tenant_api.py
──────────────────────────────────────────────────────────────────────────────
Automated Integration Tests for Multi-Tenant REST API Endpoints.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

import tenant_db
import vault
from api_server import app


@pytest.fixture
def temp_api_db():
    temp_dir = tempfile.mkdtemp(prefix="shark_api_test_")
    db_file = os.path.join(temp_dir, "test_api_trades.db")
    os.environ["ENCRYPTION_MASTER_KEY"] = vault.generate_master_key()
    tenant_db.init_tenant_db(db_file)
    os.environ["DB_PATH"] = db_file
    yield db_file
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_tenant_api_lifecycle(temp_api_db):
    """Test full multi-tenant onboarding, key vaulting, config update, and status query via REST API."""
    client = TestClient(app)

    # 1. List existing tenants (should have default admin)
    res = client.get("/api/tenants")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["count"] >= 1
    admin_id = data["tenants"][0]["id"]
    assert "admin" in data["tenants"][0]["email"]

    # 2. Register a new client tenant
    reg_payload = {
        "email": "investor1@quantcapital.com",
        "password": "SecurePassword2026!",
        "capital_base": 1500.0,
        "risk_per_trade_pct": 1.2,
        "mode": "PAPER",
        "role": "CLIENT",
    }
    res = client.post("/api/tenants/register", json=reg_payload)
    assert res.status_code == 200
    tenant_info = res.json()["tenant"]
    tenant_id = tenant_info["id"]
    assert tenant_info["email"] == "investor1@quantcapital.com"
    assert tenant_info["capital_base"] == 1500.0

    # 3. Duplicate registration should be blocked
    res_dup = client.post("/api/tenants/register", json=reg_payload)
    assert res_dup.status_code == 400
    assert "already registered" in res_dup.json()["detail"].lower()

    # 4. Store encrypted API keys in vault
    key_payload = {
        "api_key": "shark_api_live_9988776655",
        "api_secret": "shark_secret_super_secret_hash_key",
        "exchange": "SHARK",
        "nickname": "Main Subaccount Key",
    }
    res_keys = client.post(f"/api/tenants/{tenant_id}/keys", json=key_payload)
    assert res_keys.status_code == 200
    assert res_keys.json()["ok"] is True

    # Verify keys are truly encrypted in database and decryptable JIT
    k, s = tenant_db.get_tenant_keys(tenant_id, db_path=temp_api_db)
    assert k == "shark_api_live_9988776655"
    assert s == "shark_secret_super_secret_hash_key"

    # 5. Query tenant status endpoint
    res_st = client.get(f"/api/tenants/{tenant_id}/status")
    assert res_st.status_code == 200
    status_data = res_st.json()["status"]
    assert status_data["tenant_id"] == tenant_id
    assert status_data["email"] == "investor1@quantcapital.com"
    assert status_data["wallet"]["balance"] == 1500.0

    # 6. Backward-compatible /api/status?tenant_id=...
    res_compat = client.get(f"/api/status?tenant_id={tenant_id}")
    assert res_compat.status_code == 200
    compat_data = res_compat.json()
    assert compat_data["tenant_id"] == tenant_id
    assert compat_data["equity"] == 1500.0

    # 7. Update tenant risk configuration
    update_payload = {
        "capital_base": 2000.0,
        "risk_per_trade_pct": 2.0,
        "daily_loss_limit_pct": 4.0,
        "sizing_mode": "MANUAL",
        "manual_lot_size": 0.025,
        "mode": "LIVE",
    }
    res_up = client.post(f"/api/tenants/{tenant_id}/config", json=update_payload)
    assert res_up.status_code == 200
    assert res_up.json()["ok"] is True

    # Verify updated values in DB
    updated_t = tenant_db.get_tenant_by_id(tenant_id, db_path=temp_api_db)
    assert updated_t["capital_base"] == 2000.0
    assert updated_t["risk_per_trade_pct"] == 2.0
    assert updated_t["sizing_mode"] == "MANUAL"
    assert updated_t["manual_lot_size"] == 0.025
    assert updated_t["mode"] == "LIVE"

    # 8. Query trade ledger
    res_tr = client.get(f"/api/tenants/{tenant_id}/trades")
    assert res_tr.status_code == 200
    assert isinstance(res_tr.json()["trades"], list)

    # 9. Close position endpoint
    res_close = client.post(f"/api/tenants/{tenant_id}/close")
    assert res_close.status_code == 200
    assert res_close.json()["ok"] is True
