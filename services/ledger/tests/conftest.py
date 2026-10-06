from __future__ import annotations

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from tests.support import FakeHornet


@pytest.fixture
def hornet() -> FakeHornet:
    return FakeHornet()


@pytest.fixture
def client(tmp_path, hornet: FakeHornet):
    app = create_app(database_path=str(tmp_path / "ledger.db"), hornet=hornet)
    with TestClient(app) as test_client:
        yield test_client, hornet
