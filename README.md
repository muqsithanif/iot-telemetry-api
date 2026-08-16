# IoT Telemetry API

A web service that collects sensor readings from field devices and serves them back to operators. The device firmware that feeds it is in the same repository, so both ends of the link can be checked against each other rather than assumed to match.

Built with FastAPI and SQLAlchemy. It runs on SQLite with no setup at all, and runs the same code against MySQL by changing one environment variable.

---

## One observation shapes the whole design

Field devices misbehave, and the server is the only place you can do anything about it.

A sensor sitting in a factory has a weak network, a clock nobody maintains, and no operator watching it. It cannot be relied on to send clean data, and it cannot be fixed remotely when it does not. So every awkward case has to be absorbed at the receiving end, and each row below is one of those cases.

| What goes wrong in the field | What this service does |
|---|---|
| The network drops mid-delivery and the device retries the same batch | The combination of device, metric and timestamp is unique, so a repeated batch reports how many rows were duplicates instead of failing |
| A device clock drifts or resets to 1970 | Timestamps outside a configurable window are rejected, with the reason stated in the response |
| One malformed reading arrives inside a batch of fifty | The good rows are stored and the bad ones are reported individually, rather than losing all fifty |
| A device credential leaks | Device keys can only write, and cannot read anyone's data |
| An operator credential leaks | User tokens can only read, and cannot impersonate a device |

The first row is the one that shapes the rest. Because a replay is harmless, the firmware can keep its buffer after a failed send and simply try again. Making the server tolerant of repeats is what allows the device to be simple.

### Two kinds of identity, deliberately separate

A **device** authenticates with a long-lived API key sent in a header, and may only write readings for itself.

A **user** authenticates with a short-lived token obtained from a login endpoint, and may only read, unless they hold the admin role.

Keeping them apart means a stolen device key exposes nothing, since it cannot read, and a stolen user token cannot forge measurements, since it cannot write. Merging the two into one credential type would make either theft considerably worse.

---

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | — | Create a user, as admin or reader |
| `POST` | `/auth/token` | — | Exchange credentials for a token |
| `POST` | `/devices` | admin | Register a device, returning its API key once |
| `GET` | `/devices` | user | List devices |
| `GET` | `/devices/{id}` | user | One device |
| `DELETE` | `/devices/{id}` | admin | Delete a device and its readings |
| `POST` | `/readings` | **device key** | Ingest a batch of readings |
| `GET` | `/devices/{id}/readings` | user | Query by metric, time window, with pagination |
| `GET` | `/devices/{id}/summary` | user | Per-metric count, minimum, maximum, average |

Interactive documentation is generated at `/docs` once the service is running.

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

Same code, same tests, different engine. Docker is needed only for this path.

---

## A walk through the whole flow

```bash
# 1. create an admin and get a token
curl -X POST localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"operatorpass","role":"admin"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/token \
  -d "username=operator&password=operatorpass" | jq -r .access_token)

# 2. register a device. The api_key appears here and never again
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

## Schema, and two decisions inside it

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

**Two timestamps, not one.** `recorded_at` is when the device took the sample and `received_at` is when the server stored it. Keeping both means a batch that arrives an hour late is still plotted at the time it actually happened, and the delay itself remains visible.

**One index, chosen to fit the queries.** The readings table is append-only and grows fastest, so it carries a composite index on device and time. Every query filters by device first and then by time window, and that single index serves both without scanning the table. The query builders apply the filters in that same order for the same reason.

**Two different hashing choices.** Device API keys are stored as SHA-256. User passwords use bcrypt, which is deliberately slow. The difference is not inconsistency: a bcrypt hash resists guessing of human-chosen passwords, and it costs time on every check. Device keys are long random strings that cannot realistically be guessed, so slow hashing would buy nothing while adding cost to every single ingestion request.

---

## Tests

```bash
pytest -q
```

Twenty-nine tests, each against a fresh in-memory database so they can run in any order. They target behaviour rather than accessors.

- A failed login looks identical whether the password was wrong or the user does not exist, so the endpoint cannot be used to discover which accounts are real.
- A device API key is never returned again after creation.
- A replayed batch reports duplicates instead of failing.
- A batch containing one bad row still stores the good ones.
- Readers cannot register or delete devices.
- Deleting a device removes its readings rather than leaving them orphaned.

---

## Firmware

`firmware/esp32_sender/` holds an Arduino sketch for an ESP32 with a temperature and humidity sensor. It buffers samples locally, sends them in batches, timestamps each one at the moment it was sampled, and keeps the buffer intact when a send fails.

Keeping the buffer is only safe because the server treats replays as duplicates, which is the design decision from the top of this page paying off at the other end of the link.

There is one failure it does not retry. A rejected key will never succeed by trying again, so on that response the firmware drops the buffer and writes the reason to the serial log instead of growing without bound until the device runs out of memory.

---

## What this is not

A single-node service that creates its tables at startup. Running more than one instance would need proper migrations, rate limiting on ingestion, and TLS termination in front of it.

Those omissions are deliberate. The scope here is a service that works, is tested, and describes its own boundaries accurately.

---

Built by [Muqsit Muhammad Hanif](https://github.com/muqsithanif) · muqsithanif29@gmail.com
