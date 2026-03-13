"""Try connecting to each DB on localhost:5434. Run from backend: python scripts/try_databases.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# From your Spring config: localhost:5434, postgres, P@ssw0rd__!!
HOST = "localhost"
USER = "postgres"
PASSWORD = "P@ssw0rd__!!"

DB_NAMES = [
    "postgres",
    "project_tracking",
    "ai_assistant",
    "ai_database",
    "loan_system_db",
    "notes",
    "file_database",
    "visitors_database",
    "fnber_ai_database",
]


async def main():
    try:
        import asyncpg
    except ImportError:
        print("pip install asyncpg")
        return
    for port in (5434, 5432):
        print(f"\n--- port {port} ---")
        for db in DB_NAMES:
            try:
                conn = await asyncpg.connect(
                    host=HOST, port=port, user=USER, password=PASSWORD, database=db, timeout=3
                )
                await conn.close()
                print(f"  OK: {db}")
            except Exception as e:
                print(f"  FAIL: {db}  -> {e}")


if __name__ == "__main__":
    asyncio.run(main())
