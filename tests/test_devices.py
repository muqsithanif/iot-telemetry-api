def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_register_device(client, admin_token):
    res = client.post(
        "/devices",
        json={"name": "esp32-greenhouse", "location": "Rooftop"},
        headers=auth(admin_token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "esp32-greenhouse"
    # The plaintext key is returned exactly once, at creation.
    assert len(body["api_key"]) > 20


def test_reader_cannot_register_device(client, reader_token):
    res = client.post(
        "/devices", json={"name": "esp32-x"}, headers=auth(reader_token)
    )
    assert res.status_code == 403


def test_api_key_is_never_returned_again(client, admin_token, device):
    res = client.get(f"/devices/{device['id']}", headers=auth(admin_token))
    assert res.status_code == 200
    assert "api_key" not in res.json()

    listing = client.get("/devices", headers=auth(admin_token))
    assert "api_key" not in listing.text


def test_duplicate_device_name_rejected(client, admin_token, device):
    res = client.post(
        "/devices", json={"name": device["name"]}, headers=auth(admin_token)
    )
    assert res.status_code == 409


def test_reader_can_list_devices(client, reader_token, device):
    res = client.get("/devices", headers=auth(reader_token))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_missing_device_returns_404(client, admin_token):
    assert client.get("/devices/999", headers=auth(admin_token)).status_code == 404


def test_deleting_device_cascades_to_readings(client, admin_token, device):
    client.post(
        "/readings",
        json={"readings": [{"metric": "temperature", "value": 27.5, "unit": "C"}]},
        headers={"X-API-Key": device["api_key"]},
    )

    assert (
        client.delete(f"/devices/{device['id']}", headers=auth(admin_token)).status_code
        == 204
    )
    # Readings are gone with the device, not orphaned.
    assert (
        client.get(
            f"/devices/{device['id']}/readings", headers=auth(admin_token)
        ).status_code
        == 404
    )


def test_reader_cannot_delete_device(client, reader_token, device):
    res = client.delete(f"/devices/{device['id']}", headers=auth(reader_token))
    assert res.status_code == 403
