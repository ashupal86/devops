import os

# Must be set before the app is imported so the engine binds to an in-memory DB.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def profile_payload():
    return {
        "tag": "ada",
        "display_name": "Ada Lovelace",
        "message": "First programmer. Say hi!",
        "links": [
            {"label": "GitHub", "url": "https://github.com/ada"},
            {"label": "X", "url": "https://x.com/ada"},
        ],
    }


@pytest.fixture
def created(client, profile_payload):
    """A created profile; returns (profile, edit_token)."""
    res = client.post("/api/profiles", json=profile_payload)
    assert res.status_code == 201
    body = res.json()
    return body["profile"], body["edit_token"]
