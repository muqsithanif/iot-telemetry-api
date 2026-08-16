# IoT Telemetry API

A REST API that ingests sensor readings from field devices and serves them back to operators — with the ESP32 firmware that feeds it included, so both sides of the link can be verified against each other rather than assumed to match.

Built with **FastAPI**, **SQLAlchemy**, and **JWT** authentication. Runs on SQLite with no setup; runs the same code against **MySQL** by changing one environment variable.

---

## Why it is shaped this way

Most of the design here comes from one observation: **field devices misbehave, and the server is the only place you can compensate for it.**

| Problem in the field | What the API does |
|---|---|
| Network drops mid-delivery, device retries the same batch | `(device, metric, recorded_at)` is unique — a replay returns `duplicates`, not an error |
| Device clock drifts or resets | Timestamps outside a configurable window are rejected with a reason |
| One malformed reading in a batch of fifty | Good rows are stored, bad rows are reported individually |
| Device credentials leak | Device keys can only write; they cannot read anyone's data |
| Operator credentials leak | User tokens can only read; they cannot impersonate a device |

The two identities are deliberately separate. A device authenticates with a long-lived `X-API-Key` and may only write its own series. A user authenticates with a short-lived JWT and may only read, unless they hold the `admin` role.

---

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | — | Create a user (`admin` or `reader`) |
| `POST` | `/auth/token` | — | Exchange credentials for a JWT |
| `POST` | `/devices` | admin | Register a device, returns its API key **once** |
| `GET` | `/devices` | user | List devices |
| `GET` | `/devices/{id}` | user | One device |
| `DELETE` | `/devices/{id}` | admin | Delete device and its readings |
| `POST` | `/readings` | **device key** | Ingest a batch of readings |
| `GET` | `/devices/{id}/readings` | user | Query with metric, time window, pagination |
| `GET` | `/devices/{id}/summary` | user | Per-metric count, min, max, average |

Interactive docs at `/docs` once running.

---

## Running it

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then set JWT_SECRET
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>.

### Against MySQL instead

```bash
docker compose up -d
# set in .env:
# DATABASE_URL=mysql+pymysql://telemetry:telemetry@localhost:3306/telemetry
uvicorn app.main:app --reload
```

Same code, same tests, different engine. Docker is only needed for this path.

---

## Walkthrough

```bash
# 1. create an admin and get a token
curl -X POST localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"operatorpass","role":"admin"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/token \
  -d "username=operator&password=operatorpass" | jq -r .access_token)

# 2. register a device — the api_key is shown here and never again
curl -X POST localhost:8000/devices \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"esp32-lab-01","location":"Bandung"}'

# 3. the device posts a batch
curl -X POST localhost:8000/readings \
  -H "X-API-Key: <api_key>" -H "Content-Type: application/json" \
  -d '{"readings":[
        {"metric":"temperature","value":28.4,"unit":"C"},
        {"metric":"humidity","value":71.0,"unit":"%"}]}'

# 4. an operator reads it back
curl "localhost:8000/devices/1/summary" -H "Authorization: Bearer $TOKEN"
```

---

## Schema

```
users                devices                     readings
─────                ───────                     ────────
id                   id                          id
username  (unique)   name         (unique)       device_id  ──┐ FK, cascade
password_hash        location                    metric       │
role                 api_key_hash (unique)       value        │
created_at           created_at                  unit         │
                                                 recorded_at  │  when sampled
                                                 received_at  │  when stored
                                                              │
              INDEX ix_readings_device_time (device_id, recorded_at)
              UNIQUE (device_id, metric, recorded_at)
```

`readings` is append-only and grows fastest, so it carries a composite index on `(device_id, recorded_at)`. Every query filters by device and then by time window, and that one index serves both without a table scan. Query builders in `routers/readings.py` apply the filters in that order deliberately.

Device API keys are stored as SHA-256 rather than bcrypt: they are high-entropy random strings, so slow hashing buys nothing, and ingestion has to verify a key on every request. User passwords use bcrypt, where slow hashing is the point.

---

## Tests

```bash
pytest -q
```

29 tests, each against a fresh in-memory database so they can run in any order. They cover the behaviour that matters rather than the getters:

- login failures are indistinguishable between a wrong password and an unknown user, so the endpoint cannot be used to enumerate accounts
- a device API key is never returned again after creation
- a replayed batch reports duplicates instead of failing
- a batch with one bad row still stores the good rows
- readers cannot register or delete devices
- deleting a device cascades to its readings rather than orphaning them

---

## Firmware

`firmware/esp32_sender/` holds an Arduino sketch for an ESP32 with a DHT22. It buffers samples locally, batches them, timestamps each with the moment it was sampled, and keeps the buffer intact when a POST fails — which is safe precisely because the server treats replays as duplicates.

The one case it does not retry is `401`. A wrong key will never succeed by retrying, so it drops the buffer and says why in the serial log rather than growing forever.

---

## What this is not

A single-node service that creates its tables on startup. A deployment running more than one instance would need migrations (Alembic) instead, plus rate limiting on ingestion and TLS termination in front. Those are deliberate omissions, not oversights — the scope here is a working, tested, honestly documented service.

---

Built by [Muqsit Muhammad Hanif](https://github.com/muqsithanif) · muqsithanif29@gmail.com
