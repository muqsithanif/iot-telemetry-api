from datetime import datetime, timedelta, timezone


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def key(device):
    return {"X-API-Key": device["api_key"]}


def iso(dt):
    return dt.isoformat()


def test_device_can_ingest_batch(client, device):
    res = client.post(
        "/readings",
        json={
            "readings": [
                {"metric": "temperature", "value": 28.4, "unit": "C"},
                {"metric": "humidity", "value": 71.0, "unit": "%"},
            ]
        },
        headers=key(device),
    )
    assert res.status_code == 201
    assert res.json()["accepted"] == 2


def test_ingest_rejects_unknown_api_key(client):
    res = client.post(
        "/readings",
        json={"readings": [{"metric": "temperature", "value": 20.0}]},
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert res.status_code == 401


def test_ingest_requires_api_key(client):
    res = client.post(
        "/readings", json={"readings": [{"metric": "temperature", "value": 20.0}]}
    )
    assert res.status_code == 422


def test_unknown_metric_rejected(client, device):
    res = client.post(
        "/readings",
        json={"readings": [{"metric": "temperture", "value": 20.0}]},
        headers=key(device),
    )
    assert res.status_code == 422


def test_replayed_batch_counts_as_duplicate_not_error(client, device):
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    body = {
        "readings": [
            {"metric": "temperature", "value": 25.0, "recorded_at": iso(stamp)}
        ]
    }

    first = client.post("/readings", json=body, headers=key(device))
    second = client.post("/readings", json=body, headers=key(device))

    assert first.json()["accepted"] == 1
    # A device retrying after a dropped ACK must not fail the whole request.
    assert second.status_code == 201
    assert second.json() == {"accepted": 0, "duplicates": 1, "rejected": []}


def test_future_timestamp_rejected(client, device):
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    res = client.post(
        "/readings",
        json={
            "readings": [
                {"metric": "temperature", "value": 25.0, "recorded_at": iso(future)}
            ]
        },
        headers=key(device),
    )
    assert res.json()["accepted"] == 0
    assert "future" in res.json()["rejected"][0]


def test_stale_timestamp_rejected(client, device):
    stale = datetime.now(timezone.utc) - timedelta(days=10)
    res = client.post(
        "/readings",
        json={
            "readings": [
                {"metric": "temperature", "value": 25.0, "recorded_at": iso(stale)}
            ]
        },
        headers=key(device),
    )
    assert res.json()["accepted"] == 0
    assert "older than" in res.json()["rejected"][0]


def test_partial_batch_accepts_good_rejects_bad(client, device):
    future = datetime.now(timezone.utc) + timedelta(hours=6)
    res = client.post(
        "/readings",
        json={
            "readings": [
                {"metric": "temperature", "value": 25.0},
                {"metric": "humidity", "value": 60.0, "recorded_at": iso(future)},
            ]
        },
        headers=key(device),
    )
    # One bad row does not discard the good one.
    assert res.json()["accepted"] == 1
    assert len(res.json()["rejected"]) == 1


def test_query_filters_by_metric_and_window(client, device, reader_token):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post(
        "/readings",
        json={
            "readings": [
                {
                    "metric": "temperature",
                    "value": 20.0 + i,
                    "recorded_at": iso(now - timedelta(hours=i)),
                }
                for i in range(5)
            ]
            + [{"metric": "humidity", "value": 50.0}]
        },
        headers=key(device),
    )

    only_temp = client.get(
        f"/devices/{device['id']}/readings",
        params={"metric": "temperature"},
        headers=auth(reader_token),
    )
    assert len(only_temp.json()) == 5

    # Pass the timestamp through params rather than the URL string: the "+" in
    # a "+00:00" offset decodes as a space if it is not percent-encoded.
    recent = client.get(
        f"/devices/{device['id']}/readings",
        params={"metric": "temperature", "since": iso(now - timedelta(hours=2))},
        headers=auth(reader_token),
    )
    assert len(recent.json()) == 3


def test_query_is_newest_first(client, device, reader_token):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post(
        "/readings",
        json={
            "readings": [
                {
                    "metric": "weight",
                    "value": float(i),
                    "recorded_at": iso(now - timedelta(minutes=i)),
                }
                for i in range(3)
            ]
        },
        headers=key(device),
    )
    values = [
        r["value"]
        for r in client.get(
            f"/devices/{device['id']}/readings", headers=auth(reader_token)
        ).json()
    ]
    assert values == [0.0, 1.0, 2.0]


def test_query_requires_authentication(client, device):
    assert client.get(f"/devices/{device['id']}/readings").status_code == 401


def test_summary_aggregates_per_metric(client, device, reader_token):
    client.post(
        "/readings",
        json={
            "readings": [
                {"metric": "temperature", "value": 20.0},
                {"metric": "temperature", "value": 30.0},
                {"metric": "humidity", "value": 55.0},
            ]
        },
        headers=key(device),
    )

    body = client.get(
        f"/devices/{device['id']}/summary", headers=auth(reader_token)
    ).json()
    by_metric = {row["metric"]: row for row in body}

    assert by_metric["temperature"]["count"] == 2
    assert by_metric["temperature"]["minimum"] == 20.0
    assert by_metric["temperature"]["maximum"] == 30.0
    assert by_metric["temperature"]["average"] == 25.0
    assert by_metric["humidity"]["count"] == 1


def test_pagination_limit_is_capped(client, device, reader_token):
    res = client.get(
        f"/devices/{device['id']}/readings?limit=5000", headers=auth(reader_token)
    )
    assert res.status_code == 422
