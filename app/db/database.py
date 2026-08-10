from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config.settings import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Batch multi-row DML into few round trips instead of one per row.
    #
    # Only affects calls that pass a LIST of parameter sets — a single
    # `execute()` is untouched, so this changes nothing for the ~87 ordinary
    # call sites. Without it psycopg2's own `executemany` is a client-side
    # loop, so a bulk UPDATE still costs one network round trip per row;
    # that is what made the hourly importance scorer hold a transaction
    # open for ~30s and die on a dropped socket.
    executemany_mode="values_plus_batch",
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
