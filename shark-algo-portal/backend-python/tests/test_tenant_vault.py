"""
test_tenant_vault.py
──────────────────────────────────────────────────────────────────────────────
Tests for Multi-Tenant Architecture Phase 1:
  1. AES-256 Fernet Encryption & JIT Decryption
  2. Multi-Tenant Schema Creation & Password Hashing
  3. Encrypted Exchange Key Vault
  4. Cross-Tenant Data Isolation (Trades & State)
──────────────────────────────────────────────────────────────────────────────
"""

import os
import tempfile
import pytest

import vault
import tenant_db


@pytest.fixture
def temp_tenant_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tenant_db.init_tenant_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_vault_encryption_decryption():
    """Verify AES-256 encryption protects secrets and recovers exact plaintext."""
    raw_api_key = "shark_key_998877665544332211"
    raw_api_secret = "shark_sec_aabbccddeeff0011223344"

    encrypted_key = vault.encrypt_secret(raw_api_key)
    encrypted_secret = vault.encrypt_secret(raw_api_secret)

    # Ensure ciphertext is scrambled
    assert encrypted_key != raw_api_key
    assert encrypted_secret != raw_api_secret
    assert "shark" not in encrypted_key.lower()

    # Ensure decryption recovers original
    decrypted_key = vault.decrypt_secret(encrypted_key)
    decrypted_secret = vault.decrypt_secret(encrypted_secret)

    assert decrypted_key == raw_api_key
    assert decrypted_secret == raw_api_secret


def test_vault_wrong_pepper_fails():
    """Verify that ciphertext cannot be decrypted with an unauthorized key/pepper."""
    raw_secret = "sensitive_institutional_secret"
    encrypted = vault.encrypt_secret(raw_secret, master_secret="pepper_alpha")

    with pytest.raises(Exception):
        vault.decrypt_secret(encrypted, master_secret="pepper_beta")


def test_tenant_creation_and_auth(temp_tenant_db):
    """Verify tenant registration, password hashing, and authentication."""
    # Create tenant
    user = tenant_db.create_tenant(
        email="alice@investor.com",
        password="SecurePassword2026!",
        role="CLIENT",
        capital_base=500.0,
        risk_per_trade_pct=1.0,
        db_path=temp_tenant_db,
    )

    assert user["id"].startswith("usr_")
    assert user["email"] == "alice@investor.com"

    # Fetch from DB
    stored = tenant_db.get_tenant_by_id(user["id"], db_path=temp_tenant_db)
    assert stored is not None
    assert stored["capital_base"] == 500.0
    assert stored["password_hash"] != "SecurePassword2026!"

    # Verify password
    assert tenant_db.verify_password(stored["password_hash"], "SecurePassword2026!") is True
    assert tenant_db.verify_password(stored["password_hash"], "WrongPassword!") is False


def test_encrypted_credential_vault(temp_tenant_db):
    """Verify that tenant API keys are stored encrypted and decrypted JIT."""
    user = tenant_db.create_tenant(
        email="bob@fund.com",
        password="FundPassword123!",
        capital_base=5000.0,
        db_path=temp_tenant_db,
    )

    tenant_db.set_tenant_keys(
        tenant_id=user["id"],
        api_key="bob_live_api_key_888",
        api_secret="bob_live_api_secret_999",
        exchange="SHARK",
        db_path=temp_tenant_db,
    )

    # Retrieve and decrypt JIT
    dec_key, dec_sec = tenant_db.get_tenant_keys(user["id"], db_path=temp_tenant_db)
    assert dec_key == "bob_live_api_key_888"
    assert dec_sec == "bob_live_api_secret_999"


def test_cross_tenant_data_isolation(temp_tenant_db):
    """Ensure complete boundary isolation between Alice's and Bob's trades and wallet state."""
    alice = tenant_db.create_tenant("alice@hedge.com", "passA", capital_base=500.0, db_path=temp_tenant_db)
    bob = tenant_db.create_tenant("bob@hedge.com", "passB", capital_base=2500.0, db_path=temp_tenant_db)

    # Record trade for Alice
    trade_alice = {
        "id": "TR-ALICE-1",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "qty": 0.021,
        "entry": 76000.0,
        "exit": 76800.0,
        "pnl": 16.80,
        "reason": "15m DC Breakout",
    }
    tenant_db.record_tenant_trade(alice["id"], trade_alice, mode="LIVE", db_path=temp_tenant_db)

    # Record trade for Bob
    trade_bob = {
        "id": "TR-BOB-1",
        "symbol": "BTCUSDT",
        "side": "SHORT",
        "qty": 0.104,
        "entry": 76500.0,
        "exit": 76100.0,
        "pnl": 41.60,
        "reason": "15m DC Breakdown",
    }
    tenant_db.record_tenant_trade(bob["id"], trade_bob, mode="LIVE", db_path=temp_tenant_db)

    # Verify Alice sees ONLY her trades
    alice_trades = tenant_db.get_tenant_trades(alice["id"], db_path=temp_tenant_db)
    assert len(alice_trades) == 1
    assert alice_trades[0]["id"] == "TR-ALICE-1"
    assert alice_trades[0]["qty"] == 0.021

    # Verify Bob sees ONLY his trades
    bob_trades = tenant_db.get_tenant_trades(bob["id"], db_path=temp_tenant_db)
    assert len(bob_trades) == 1
    assert bob_trades[0]["id"] == "TR-BOB-1"
    assert bob_trades[0]["qty"] == 0.104

    # Verify state isolation
    tenant_db.set_tenant_state(alice["id"], {"paper_wallet": 516.80, "daily_pnl": 16.80}, db_path=temp_tenant_db)
    tenant_db.set_tenant_state(bob["id"], {"paper_wallet": 2541.60, "daily_pnl": 41.60}, db_path=temp_tenant_db)

    alice_state = tenant_db.get_tenant_state(alice["id"], db_path=temp_tenant_db)
    bob_state = tenant_db.get_tenant_state(bob["id"], db_path=temp_tenant_db)

    assert alice_state["paper_wallet"] == 516.80
    assert bob_state["paper_wallet"] == 2541.60
