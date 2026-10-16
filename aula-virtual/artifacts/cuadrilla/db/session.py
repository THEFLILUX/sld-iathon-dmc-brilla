"""PostgreSQL connection: DATABASE_URL, or an embedded local server when it is empty."""

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from config import settings


def database_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    from db.local_pg import uri
    return uri(settings.LOCAL_DIR / "postgres")


def build_engine():
    url = make_url(database_url())
    if url.get_backend_name() not in {"postgres", "postgresql"}:
        raise RuntimeError("El aula virtual DMC necesita PostgreSQL.")
    return create_engine(url.set(drivername="postgresql+psycopg"), pool_pre_ping=True)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
