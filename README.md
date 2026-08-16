# IoT Telemetry API

A REST API that ingests sensor readings from field devices and serves them back to operators. The ESP32 firmware that feeds it ships in the same repository, so both sides of the link can be verified against each other.

Built with FastAPI, SQLAlchemy, and JWT authentication. Runs on SQLite without setup, and runs the same code against MySQL by changing one environment variable.

---

## Why it is shaped this way

One observation drives most of the design: field devices misbehave, and the server is the only place to compensate.

| Problem in the field | Response in the API |
|---|---|
| Network drops mid-delivery and the device retries the same batch | `(device, metric, recorded_at)` is unique, so a replay returns `duplicates` instead of an error |
| Device clock drifts or resets | Timestamps outside a configurable window are rejected with a stated reason |
| One malformed reading arrives in a batch of fifty | Good rows are stored and bad rows are reported individually |
| Device credentials leak | Device keys can write and cannot read anyone's data |
| Operator credentials leak | User tokens can read and cannot impersonate a device |

The two identities stay separate by design. A device authenticates with a long-lived `X-API-Key` and may write only its own series. A user authenticates with a short-lived JWT and may only read, unless they hold the `admin` role.

---

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | — | Create a user (`admin` or `reader`) |
| `POST` | `/auth/token` | — | Exchange credentials for a JWT |
| `POST` | `/devices` | admin | Register a device, returning its API key once |
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

Same code, same tests, different engine. Docker is required only for this path.

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

The `readings` table is append-only and grows fastest, so it carries a composite index on `(device_id, recorded_at)`. Every query filters by device and then by time window, and that single index serves both without a table scan. The query builders in `routers/readings.py` apply the filters in that order for the same reason.

Device API keys are stored as SHA-256 rather than bcrypt. They are high-entropy random strings, so slow hashing adds no protection, and ingestion verifies a key on every request. User passwords use bcrypt, where slow hashing is the purpose.

---

## Tests

```bash
pytest -q
```

29 tests, each against a fresh in-memory database so they run in any order. They cover behaviour rather than accessors:

- Login failures look identical for a wrong password and an unknown user, so the endpoint cannot enumerate accounts
- A device API key is never returned again after creation
- A replayed batch reports duplicates instead of failing
- A batch containing one bad row still stores the good rows
- Readers cannot register or delete devices
- Deleting a device cascades to its readings rather than orphaning them

---

## Firmware

`firmware/esp32_sender/` holds an Arduino sketch for an ESP32 with a DHT22. It buffers samples locally, batches them, timestamps each one at the moment of sampling, and keeps the buffer intact when a POST fails. Retaining the buffer is safe because the server treats replays as duplicates.

The sketch does not retry on `401`. A wrong key cannot succeed through retries, so the firmware drops the buffer and records the reason in the serial log instead of growing without bound.

---

## What this is not

A single-node service that creates its tables at startup. A deployment running more than one instance would need Alembic migrations, rate limiting on ingestion, and TLS termination in front. Those omissions are deliberate. The scope here is a working, tested, documented service.

---

Built by [Muqsit Muhammad Hanif](https://github.com/muqsithanif) · muqsithanif29@gmail.com
