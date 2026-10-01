"""
api/dependencies.py

FastAPI dependency that yields a SQLAlchemy session per request.
"""
from collections.abc import Generator
from sqlalchemy.orm import Session
from db.session import get_session_factory


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db: Session = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
