from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config.settings import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Recycle idle connections in the pool every 5 min — keeps them fresh
    # against Railway's proxy which drops sockets that go quiet.
    pool_recycle=300,
    # TCP keepalives so long-running transactions (bot waits ~60 min for
    # the meeting to end) don't have their socket killed as "idle" by
    # NAT / Railway proxy in between DB writes.
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        # Larger statement timeout so a single big transcript_raw update
        # (~600KB JSON) doesn't get chopped mid-write on a slow link.
        "options": "-c statement_timeout=120000",
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
