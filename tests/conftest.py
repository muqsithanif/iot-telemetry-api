"""Test fixtures.

Each test gets a fresh in-memory database so tests cannot leak state into each
other and can run in any order.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection, so :memory: survives
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token(client):
    client.post(
        "/auth/register",
        json={"username": "admin", "password": "adminpassword", "role": "admin"},
    )
    res = client.post(
        "/auth/token", data={"username": "admin", "password": "adminpassword"}
    )
    return res.json()["access_token"]


@pytest.fixture
def reader_token(client):
    client.post(
        "/auth/register",
        json={"username": "reader", "password": "readerpassword", "role": "reader"},
    )
    res = client.post(
        "/auth/token", data={"username": "reader", "password": "readerpassword"}
    )
    return res.json()["access_token"]


@pytest.fixture
def device(client, admin_token):
    res = client.post(
        "/devices",
        json={"name": "esp32-lab-01", "location": "Bandung lab"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return res.json()
