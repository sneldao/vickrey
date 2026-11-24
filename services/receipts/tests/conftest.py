from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.support import CountingSettlementAdapter, FixedClock, StaticRemoteAdapter


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def settings(tmp_path: Path, private_key: Ed25519PrivateKey) -> Settings:
    public_hex = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    return Settings.from_env(
        {
            "RECEIPTS_MODE": "demo",
            "RECEIPTS_DATABASE_PATH": str(tmp_path / "receipts.db"),
            "RECEIPTS_VERIFIER_PUBLIC_KEY": public_hex,
            "RECEIPTS_QUOTA_PER_HOUR": "1000",
        }
    )


@pytest.fixture
def remote_adapter() -> StaticRemoteAdapter:
    return StaticRemoteAdapter("insufficient")


@pytest.fixture
def settlement_adapter() -> CountingSettlementAdapter:
    return CountingSettlementAdapter()


@pytest.fixture
def make_app(settings: Settings, clock: FixedClock):
    def factory(*, remote=None, settlement=None, config=None, database_path=None):
        config = config or settings
        return create_app(
            config,
            remote_adapter=remote,
            settlement_adapter=settlement,
            clock=clock,
        )

    return factory


@pytest.fixture
def client(
    make_app,
    remote_adapter: StaticRemoteAdapter,
    settlement_adapter: CountingSettlementAdapter,
):
    app = make_app(remote=remote_adapter, settlement=settlement_adapter)
    with TestClient(app) as test_client:
        yield test_client
