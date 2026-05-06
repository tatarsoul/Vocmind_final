import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def ensure_database_exists():
    admin_engine = create_engine(settings.postgres_admin_url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
            {"db_name": settings.postgres_db},
        ).scalar()

        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))

    admin_engine.dispose()


ensure_database_exists()

engine = create_engine(settings.db_url, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()