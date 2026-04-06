# utils/connect_db.py
import os
import psycopg2
from dotenv import load_dotenv

from langchain_openai import OpenAIEmbeddings

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBED_MODEL = "text-embedding-3-small"

# Global embedding model used by policy RAG
emb = OpenAIEmbeddings(
    model=EMBED_MODEL,
    api_key=OPENAI_API_KEY,
)

DB_CONN = dict(
    dbname="fintechdb",
    user="postgres",
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", 5432)),
)

POLICY_TABLE = "vectordb.policy_docs"


def get_conn():
    """Create a new psycopg2 connection using the shared DB_CONN config."""
    return psycopg2.connect(**DB_CONN)
