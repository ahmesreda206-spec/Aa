# Qwen Farm v2

A same-origin, local-first farm operations application: FastAPI + SQLAlchemy/SQLite, a strict-CSP vanilla JavaScript PWA, lazy Llama 14B + LoRA inference, and token-authenticated ESP32 telemetry.

## Directory structure

```text
backend/
  main.py                 FastAPI entry, security headers, errors, static serving
  config.py               Environment-based production settings
  database.py             SQLite WAL, foreign keys, ORM session lifecycle
  models.py               Users, revocable sessions, devices, telemetry, chat, audit
  schemas.py              Strict Pydantic request/response contracts
  security.py             Argon2id, JWT, cookies, CSRF, HMAC device tokens
  dependencies.py         Authentication, CSRF, administrator authorization
  rate_limit.py           SlowAPI limiter
  routers/                auth, dashboard, ai, iot endpoints
  services/               serialized local inference and audit logging
frontend/
  index.html              Accessible operations wall, AI console, device fleet
  manifest.json           Installable PWA manifest
  sw.js                   Offline app shell; private API responses are never cached
  static/                 App, styles, globe, local Three.js/fonts/geometry/icons
models/llama_14b_lora/
  adapter_config.json     PEFT LoRA configuration
  chat_template.jinja     Llama header/EOT prompt format
firmware/esp32_telemetry/ Arduino HTTPS telemetry client
deploy/nginx.conf          TLS reverse proxy and edge rate limits
tests/                    Authentication, CSRF, IoT, validation, security tests
Dockerfile                 Non-root Python runtime
Docker Compose             Persistent data and optional Nginx production profile
```

## Run locally

Python 3.12 is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export QWEN_ENVIRONMENT=development
export QWEN_COOKIE_SECURE=false
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. If the database has no users, the UI presents one-time administrator setup. For an exposed fresh instance, set `QWEN_BOOTSTRAP_TOKEN` first and enter that token in the setup form. Once an administrator exists, the bootstrap route permanently returns 409.

Without `QWEN_SECRET_KEY`, a random key is created with mode 0600 at `data/.session-secret`. Set an explicit high-entropy key in managed deployments so the key lifecycle is controlled by your secret manager.

## Docker and Nginx

```bash
cp .env.example .env
# Fill QWEN_SECRET_KEY and QWEN_BOOTSTRAP_TOKEN with independent random values.
docker compose up --build -d
```

The local application is bound to `127.0.0.1:8000`. For the TLS reverse proxy, place `fullchain.pem` and `privkey.pem` in `deploy/certs/`, set `QWEN_COOKIE_SECURE=true` and your public `QWEN_ALLOWED_HOSTS`, then run:

```bash
docker compose --profile production up --build -d
```

The Compose application has a read-only root filesystem, no Linux capabilities, a non-root UID, and a persistent `/app/data` volume. Nginx redirects HTTP to HTTPS, accepts only TLS 1.2/1.3, limits request bodies, and adds edge rate limits. Service Workers require HTTPS outside localhost.

## Enable the local Llama + LoRA runtime

1. Put the complete Llama 14B base model in `models/llama_14b_base/`, including `config.json`, tokenizer files, and safetensors weights.
2. Put trained PEFT weights at `models/llama_14b_lora/adapter_model.safetensors`. The supplied `adapter_config.json` and `chat_template.jinja` are already in place.
3. For a host installation: `pip install -r requirements-ai.txt`.
4. For Docker: set `INSTALL_AI=true` and `QWEN_AI_ENABLED=true` before building.

The model loads on the first chat request and generation is serialized to bound memory use. Base and adapter files are opened in local-only mode; no Hugging Face download occurs at runtime. If runtime packages or weights are absent, `/api/ai/chat` returns 503 and the UI displays an explicit runtime notice. It never fabricates an AI response.

For CUDA deployments, use the PyTorch build appropriate for your driver/CUDA version and verify that the container has GPU access. The default optional AI installation is portable CPU inference and therefore slow for a 14B model.

## ESP32 enrollment and firmware

1. Sign in as an administrator and open **Devices → Enroll device**.
2. Copy the one-time token. The database stores only its keyed HMAC-SHA-256 digest.
3. Install ArduinoJson and the DHT sensor library in Arduino IDE.
4. Copy `firmware/esp32_telemetry/secrets.h.example` to `secrets.h` and fill Wi-Fi, device, API, and PEM CA values. Never commit `secrets.h`.
5. Adjust ADC calibration constants for the actual sensors and flash `esp32_telemetry.ino`.

The firmware validates the server certificate, synchronizes UTC time, sends strict JSON, and authenticates with `X-IoT-Token`. Disabling a device immediately revokes ingest access while preserving history.

Example request:

```bash
curl -X POST https://farm.example.com/api/iot/telemetry \
  -H 'Content-Type: application/json' \
  -H "X-IoT-Token: $IOT_TOKEN" \
  --data '{"device_id":"qf-example","temperature_c":24.8,"humidity_pct":61,"soil_moisture_pct":42,"water_level_pct":78,"battery_v":3.92,"rssi_dbm":-61}'
```

## API summary

| Method | Route | Access |
|---|---|---|
| GET | `/health` | Public, rate limited |
| POST | `/api/auth/bootstrap` | Only when no user exists |
| POST | `/api/auth/login` | Public, rate limited |
| GET | `/api/auth/session` | Public, non-error session probe |
| GET | `/api/auth/me` | Operator session |
| POST | `/api/auth/logout` | Session + CSRF |
| GET | `/api/dashboard/summary` | Operator session |
| GET/POST | `/api/ai/history`, `/api/ai/chat` | Session; mutations require CSRF |
| DELETE | `/api/ai/history` | Session + CSRF |
| GET/POST | `/api/iot/devices` | Session; enrollment requires admin + CSRF |
| DELETE | `/api/iot/devices/{id}` | Admin + CSRF |
| POST | `/api/iot/telemetry` | ESP32 `X-IoT-Token` |
| GET | `/api/iot/telemetry` | Operator session |

## Security behavior

- Argon2id password hashing and generic login failures.
- Signed, audience/issuer-validated JWTs in Secure, HttpOnly, SameSite=Strict cookies.
- Database-backed session IDs allow immediate revocation; expired sessions are purged on login.
- Double-submit CSRF tokens are additionally bound to the server-side session.
- Pydantic forbids unknown fields and constrains lengths, ranges, IDs, and telemetry timestamps.
- SQLAlchemy expression APIs provide parameterized persistence; no string-built SQL is used.
- SlowAPI limits authentication, chat, enrollment, and telemetry independently.
- Strict script/style CSP, no inline scripts, no third-party browser calls, HSTS behind HTTPS, frame denial, and no API response caching.
- Production API documentation is disabled; unexpected exceptions return a request ID without a stack trace.

## Verification

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check backend tests
```

The PWA requires no Node build or runtime. All browser dependencies are vendored. See `CREDITS.md` for third-party notices.
