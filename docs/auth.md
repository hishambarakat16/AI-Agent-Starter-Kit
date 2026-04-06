# Authentication Guide

This project uses JWT Bearer token auth. This guide covers how the login flow works, how users are stored, how to add users, and how to configure tokens.

---

## How It Works

```
POST /auth/login  { username: email, password: password }
         │
         ▼
  Look up user by email
  in core.app_users (PostgreSQL)
         │
         ▼
  bcrypt.verify(password, stored_hash)
         │ fail → 401 Unauthorized
         │ pass ↓
         ▼
  Create JWT  { sub: email, exp: now + JWT_EXPIRES_MIN }
  Sign with JWT_SECRET_KEY
         │
         ▼
  { "access_token": "eyJ...", "token_type": "bearer" }
```

Every subsequent request passes the token in the header:

```
Authorization: Bearer eyJ...
```

The `get_current_user` dependency in `app/auth/oauth2.py` decodes the token, extracts the email, and makes it available to any route that needs it.

---

## User Table

Users are stored in `core.app_users`, created automatically by `docker/initdb/01_schema.sql` when PostgreSQL first starts:

```sql
CREATE TABLE core.app_users (
  user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         citext UNIQUE NOT NULL,   -- case-insensitive email matching
  password_hash text NOT NULL,            -- bcrypt hash, never plaintext
  is_active     boolean DEFAULT true,     -- set false to disable without deleting
  created_at    timestamptz DEFAULT now()
);
```

Inactive users (`is_active = false`) are rejected at login with `403 Forbidden` before the password is even checked.

---

## Adding Users

The init scripts create the table but don't seed any users. Add them before running the app.

### Option 1 — backfill script (if you have existing data)

```bash
python scripts/backfill_app_users.py
```

Edit the script first to match your data source.

### Option 2 — insert directly

```python
import bcrypt
import psycopg2

password_hash = bcrypt.hashpw(b"yourpassword", bcrypt.gensalt()).decode()

conn = psycopg2.connect(
    host="localhost", port=5432,
    dbname="myapp", user="postgres", password="yourpassword"
)
with conn.cursor() as cur:
    cur.execute(
        "INSERT INTO core.app_users (email, password_hash) VALUES (%s, %s)",
        ("user@example.com", password_hash)
    )
conn.commit()
conn.close()
```

### Option 3 — psql inside Docker

```bash
# Hash a password
python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"

# Insert
docker exec -it agent-postgres psql -U postgres -d myapp -c \
  "INSERT INTO core.app_users (email, password_hash) VALUES ('user@example.com', '\$2b\$12\$...');"
```

---

## JWT Configuration

Three environment variables control token behaviour:

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET_KEY` | **required** | Signing key — minimum 32 chars, never commit this |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm (`HS256`, `RS256`, etc.) |
| `JWT_EXPIRES_MIN` | `60` | Token lifetime in minutes |

Generate a strong key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Relevant Files

| File | What it does |
|---|---|
| `app/auth/oauth2.py` | `get_current_user` FastAPI dependency — validates token on every protected route |
| `app/auth/token.py` | `create_access_token()` and `verify_token()` using python-jose |
| `app/auth/hashing.py` | `Hash.bcrypt()` and `Hash.verify()` using bcrypt |
| `app/routers/authentication.py` | `POST /auth/login` route — DB lookup, password check, token issuance |
| `docker/initdb/01_schema.sql` | Creates `core.app_users` table on first boot |
