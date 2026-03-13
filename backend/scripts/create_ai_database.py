"""
One-time: create ai_database on the Postgres server the app uses (localhost by default).
Run from backend/: python scripts/create_ai_database.py
Uses DATABASE_URL from .env; connects to maintenance DB 'postgres' to create ai_database.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings

# Connect to maintenance DB to create ai_database
url = settings.database_url.replace("+asyncpg", "").strip()
if "/ai_database" in url:
    maintenance_url = url.rsplit("/", 1)[0] + "/postgres"
else:
    maintenance_url = url

def main():
    try:
        import psycopg2
    except ImportError:
        print("Install psycopg2-binary: pip install psycopg2-binary")
        sys.exit(1)
    # Parse simple postgresql://user:pass@host:port/db
    from urllib.parse import urlparse, unquote
    p = urlparse(maintenance_url)
    user = unquote(p.username or "postgres")
    password = unquote(p.password or "")
    host = p.hostname or "localhost"
    port = p.port or 5432
    db = p.path.lstrip("/") or "postgres"
    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=db,
        connect_timeout=5,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'ai_database'")
    if cur.fetchone():
        print("Database ai_database already exists.")
    else:
        cur.execute('CREATE DATABASE ai_database')
        print("Created database ai_database.")
    cur.close()
    conn.close()
    # Enable pgvector in ai_database
    from urllib.parse import urlparse as up2
    u2 = urlparse(settings.database_url.replace("+asyncpg", ""))
    conn2 = psycopg2.connect(
        host=u2.hostname or "localhost",
        port=u2.port or 5432,
        user=unquote(u2.username or "postgres"),
        password=unquote(u2.password or ""),
        dbname="ai_database",
        connect_timeout=5,
    )
    conn2.autocommit = True
    cur2 = conn2.cursor()
    try:
        cur2.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("Ensured vector extension in ai_database.")
    except Exception as e:
        print("Note: vector extension not available:", e)
    cur2.close()
    conn2.close()
    print("Done. Run: alembic upgrade head")

if __name__ == "__main__":
    main()
