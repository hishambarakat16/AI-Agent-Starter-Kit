import os
import psycopg2
from dotenv import load_dotenv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from passlib.context import CryptContext
from app.auth.hashing import Hash


load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "Admin@123")
DEFAULT_HASH = Hash.bcrypt(DEFAULT_PASSWORD)

DB_CONN = dict(
    dbname=os.getenv("POSTGRES_DB", "fintechdb"),
    user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
)

def main() -> None:
    with psycopg2.connect(**DB_CONN) as conn:
        with conn.cursor() as cur:
            # Create table if not exists
            cur.execute("""
                INSERT INTO core.app_users (email, password_hash, customer_id, is_active)
                SELECT
                    COALESCE(NULLIF(c.email, ''), ('user_' || left(c.customer_id::text, 8) || '@example.com')) AS email,
                    %s AS password_hash,
                    c.customer_id,
                    TRUE
                FROM core.customers c
                ON CONFLICT (email) DO NOTHING;
            """, (DEFAULT_HASH,))

            cur.execute("SELECT COUNT(*) FROM core.app_users;")
            print("core.app_users rows:", cur.fetchone()[0])

if __name__ == "__main__":
    main()
