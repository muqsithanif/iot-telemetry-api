def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_then_login(client):
    res = client.post(
        "/auth/register",
        json={"username": "budi", "password": "supersecret", "role": "reader"},
    )
    assert res.status_code == 201
    assert res.json()["role"] == "reader"
    assert "password" not in res.text and "hash" not in res.text

    res = client.post("/auth/token", data={"username": "budi", "password": "supersecret"})
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"


def test_duplicate_username_rejected(client):
    payload = {"username": "budi", "password": "supersecret"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_short_password_rejected(client):
    res = client.post("/auth/register", json={"username": "budi", "password": "short"})
    assert res.status_code == 422


def test_unknown_role_rejected(client):
    res = client.post(
        "/auth/register",
        json={"username": "budi", "password": "supersecret", "role": "superuser"},
    )
    assert res.status_code == 422


def test_wrong_password_gives_same_error_as_unknown_user(client):
    client.post("/auth/register", json={"username": "budi", "password": "supersecret"})

    wrong_password = client.post(
        "/auth/token", data={"username": "budi", "password": "wrongpassword"}
    )
    unknown_user = client.post(
        "/auth/token", data={"username": "nobody", "password": "wrongpassword"}
    )

    # Identical responses, so the endpoint cannot be used to enumerate accounts.
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_protected_route_rejects_missing_token(client):
    assert client.get("/devices").status_code == 401


def test_protected_route_rejects_garbage_token(client):
    res = client.get("/devices", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401
