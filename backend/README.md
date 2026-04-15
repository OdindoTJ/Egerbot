# EgerBot Backend

Flask API backend for EgerBot — the Egerton University intelligent assistant.

---

## Project Structure

```
egerbot-backend/
├── app.py                        # Flask entry point — registers all blueprints
├── egerbot_system_prompt.txt     # System prompt template (copy from your prompt file)
├── requirements.txt
├── Procfile                      # For Render / Railway deployment
├── .env.example                  # Copy to .env and fill in your keys
├── .gitignore
│
├── config/
│   ├── settings.py               # All env vars loaded and validated here
│   └── supabase.py               # Shared Supabase client + connection test
│
├── routes/
│   ├── health.py                 # GET /health, GET /health/full
│   ├── chat.py                   # /api/greeting, /api/session/*, /api/chat, /api/feedback
│   └── admin.py                  # /api/admin/* (all protected)
│
├── services/
│   ├── knowledge.py              # Fetches all KB tables from Supabase
│   ├── prompt.py                 # Assembles system prompt from template + KB data
│   └── llm.py                    # Calls Anthropic API, detects escalations
│
├── utils/
│   ├── auth.py                   # require_admin decorator, token helpers
│   └── language.py               # Swahili/English detection
│
└── tests/
    ├── test_health.py
    ├── test_chat.py
    └── test_admin.py
```

---

## 1. Initial Setup

### Clone and create virtual environment

```bash
git clone <your-repo-url>
cd egerbot-backend

python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Variable | Where to find it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `SUPABASE_URL` | Supabase Dashboard → Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Dashboard → Settings → API → service_role key |

Place your `egerbot_system_prompt.txt` in the root of the project folder.

---

## 2. Supabase Connection

EgerBot connects to Supabase using the **service role key** — this key bypasses
Row Level Security and allows the backend to read and write all tables.

**Never expose the service role key on the frontend.**
It must only ever be in your backend `.env` file.

### Verify your connection

```bash
python - <<'EOF'
from config.supabase import test_connection
result = test_connection()
print(result)
EOF
```

Expected output if connected:
```
{'status': 'connected', 'error': None}
```

If you see an error, check:
1. `SUPABASE_URL` ends with `.supabase.co` — no trailing slash
2. `SUPABASE_SERVICE_ROLE_KEY` is the `service_role` key, NOT the `anon` key
3. Your Supabase project is not paused (free tier pauses after inactivity)

### Create the first admin user

Run this once in your Supabase SQL editor to create the first admin account.
Replace the values with real ones:

```sql
INSERT INTO admin_users (name, email, password_hash, role)
VALUES (
  'Admin Name',
  'admin@egerton.ac.ke',
  -- Generate this hash using Python: python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
  '$2b$12$your_bcrypt_hash_here',
  'superadmin'
);
```

Copy the output and paste it into the SQL above.

---


## 4. Testing the API

### Quick health check (no DB required)

```bash
curl http://localhost:5000/health
```

Expected:
```json
{"status": "ok", "bot": "EgerBot", "model": "claude-sonnet-4-6"}
```

### Full health check (tests Supabase connection)

```bash
curl http://localhost:5000/health/full
```

Expected when connected:
```json
{
  "status": "ok",
  "bot": "EgerBot",
  "model": "claude-sonnet-4-6",
  "database": {"status": "connected", "error": null}
}
```

### Get greeting messages

```bash
curl http://localhost:5000/api/greeting
```

### Start a chat session

```bash
curl -X POST http://localhost:5000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"user_type": "prospective"}'
```

Expected:
```json
{"session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}
```

### Send a chat message

Replace `YOUR_SESSION_ID` with the value from the step above:

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "YOUR_SESSION_ID",
    "message": "What courses does Egerton University offer?"
  }'
```

Expected:
```json
{
  "response": "Egerton University offers programmes across 10 faculties...",
  "language": "en",
  "session_id": "YOUR_SESSION_ID",
  "chat_log_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "escalated": false,
  "quick_replies": [...]
}
```

### Test Swahili detection

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "YOUR_SESSION_ID",
    "message": "Ninahitaji kujua kuhusu masomo ya uhandisi"
  }'
```

Expected: `"language": "sw"` in the response.

### Submit feedback

Replace `YOUR_CHAT_LOG_ID` with the `chat_log_id` from a chat response:

```bash
curl -X POST http://localhost:5000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "chat_log_id": "YOUR_CHAT_LOG_ID",
    "rating": 5,
    "comment": "Very helpful!"
  }'
```

### End a session

```bash
curl -X POST http://localhost:5000/api/session/end \
  -H "Content-Type: application/json" \
  -d '{"session_id": "YOUR_SESSION_ID"}'
```

### Admin login

```bash
curl -X POST http://localhost:5000/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@egerton.ac.ke",
    "password": "YourPassword123"
  }'
```

Expected:
```json
{
  "token": "your_raw_token_here",
  "name": "Admin Name",
  "role": "superadmin",
  "email": "admin@egerton.ac.ke"
}
```

### Use the admin token (replace TOKEN with value from login)

```bash
# View analytics
curl http://localhost:5000/api/admin/analytics \
  -H "Authorization: Bearer TOKEN"

# View unanswered questions
curl http://localhost:5000/api/admin/unanswered \
  -H "Authorization: Bearer TOKEN"

# View system config
curl http://localhost:5000/api/admin/config \
  -H "Authorization: Bearer TOKEN"

# Update a config value
curl -X PATCH http://localhost:5000/api/admin/config/escalation_email \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"config_value": "newemail@egerton.ac.ke"}'

# View chat logs (paginated)
curl "http://localhost:5000/api/admin/logs?page=1&limit=20" \
  -H "Authorization: Bearer TOKEN"
```

---

## 5. Running Automated Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_health.py -v
pytest tests/test_chat.py -v
pytest tests/test_admin.py -v

# Run with coverage report
pytest tests/ -v --tb=short
```

### What each test file covers

| File | What it tests |
|---|---|
| `test_health.py` | Health endpoints return correct status and structure |
| `test_chat.py` | Session creation, message sending, language detection, feedback |
| `test_admin.py` | Auth rejection without token, login validation, protected routes |

### Note on integration tests

`test_chat_full_flow` in `test_chat.py` makes a real call to Supabase and Anthropic.
It requires your `.env` to be configured with valid credentials.
All other tests only check request validation and response structure.

---

## 6. API Reference Summary

| Method | Route | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | None | Liveness check |
| GET | `/health/full` | None | Liveness + DB connection check |
| GET | `/api/greeting` | None | Get opening greeting messages |
| POST | `/api/session/start` | None | Create new chat session |
| POST | `/api/chat` | None | Send message, get bot response |
| POST | `/api/feedback` | None | Submit rating for a response |
| POST | `/api/session/end` | None | End a chat session |
| POST | `/api/admin/login` | None | Admin login, returns token |
| POST | `/api/admin/logout` | Bearer | Revoke token |
| GET | `/api/admin/analytics` | Bearer | Dashboard headline stats |
| GET | `/api/admin/unanswered` | Bearer | List unanswered questions |
| PATCH | `/api/admin/unanswered/<id>` | Bearer | Mark reviewed/resolved |
| GET | `/api/admin/config` | Bearer | All system config values |
| PATCH | `/api/admin/config/<key>` | Bearer | Update a config value |
| GET | `/api/admin/faqs` | Bearer | List all FAQs |
| POST | `/api/admin/faqs` | Bearer | Create new FAQ |
| PATCH | `/api/admin/faqs/<id>` | Bearer | Update FAQ |
| DELETE | `/api/admin/faqs/<id>` | Bearer | Delete FAQ |
| GET | `/api/admin/quick-replies` | Bearer | List quick replies |
| POST | `/api/admin/quick-replies` | Bearer | Create quick reply |
| PATCH | `/api/admin/quick-replies/<id>` | Bearer | Update quick reply |
| DELETE | `/api/admin/quick-replies/<id>` | Bearer | Delete quick reply |
| GET | `/api/admin/logs` | Bearer | Paginated chat logs |

---

## 7. Deployment to Render (Free Tier)

1. Push your project to GitHub (make sure `.env` is in `.gitignore`)
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Set Build Command: `pip install -r requirements.txt`
5. Set Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
6. Under Environment Variables, add all keys from your `.env` file
7. Deploy — Render will give you a public URL like `https://egerbot.onrender.com`
