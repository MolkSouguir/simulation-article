"""
db/session.py

Database engine and sessions. For the command-line scripts it can also start
the PostgreSQL Windows service and create the database if they're missing.

Usage:
    from db.session import get_session, engine

    with get_session() as session:
        session.add(some_model)
        session.commit()
"""
import os
import time
import subprocess
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from collections.abc import Iterator
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:psql@localhost:5432/simulationapp")
POSTGRES_SERVICE_NAME = os.getenv("POSTGRES_SERVICE_NAME", "postgresql-x64-14")

# Same server, default 'postgres' database: needed to run CREATE DATABASE.
_admin_url = DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
_db_name = DATABASE_URL.rsplit("/", 1)[-1]


def _is_service_running() -> bool:
    result = subprocess.run(
        ["sc", "query", POSTGRES_SERVICE_NAME],
        capture_output=True, text=True
    )
    return "RUNNING" in result.stdout


def _start_postgres_service():
    """Start the PostgreSQL Windows service (needs administrator rights)."""
    print(f"[DB] PostgreSQL service not running. Starting '{POSTGRES_SERVICE_NAME}'...")
    result = subprocess.run(
        ["net", "start", POSTGRES_SERVICE_NAME],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to start PostgreSQL service '{POSTGRES_SERVICE_NAME}'.\n"
            f"Please start it manually:\n"
            f"  net start {POSTGRES_SERVICE_NAME}\n"
            f"Or run your terminal / app as Administrator.\n\n"
            f"Details: {result.stderr.strip()}"
        )
    # Give it up to 10 seconds to accept connections
    for _ in range(10):
        time.sleep(1)
        try:
            temp_engine = create_engine(_admin_url, pool_pre_ping=True)
            with temp_engine.connect():
                temp_engine.dispose()
                print("[DB] PostgreSQL is ready.")
                return
        except Exception:
            continue
    raise RuntimeError("PostgreSQL started but is not accepting connections after 10 seconds.")


def _ensure_database_exists():
    """Create the target database if it does not already exist."""
    admin_engine = create_engine(_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": _db_name}
            ).fetchone()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{_db_name}"'))
                print(f"[DB] Database '{_db_name}' created.")
            else:
                print(f"[DB] Database '{_db_name}' already exists.")
    finally:
        admin_engine.dispose()


def ensure_postgres_ready():
    """
    Make sure the PostgreSQL service is running and the database exists.
    Call it once at startup, before anything else touches the database.
    """
    if not _is_service_running():
        _start_postgres_service()
    else:
        print("[DB] PostgreSQL service is already running.")
    _ensure_database_exists()


# Created on first use, so importing this module doesn't connect to anything.
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """A session that commits when the block ends, or rolls back on an error."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
