from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declared_attr


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base_Entity:
    """Mix in to any declarative model to get a bigint PK + audit columns.

    `id` is the default bigint auto-increment primary key. A concrete model
    that declares its own `id` (Integer / UUID / BigInteger) overrides this
    one — Python attribute resolution means the subclass column wins — so
    existing tables keep their current PK type. New models that don't declare
    an `id` inherit this bigint PK.
    """

    id = Column(Integer, primary_key=True, autoincrement=True)

    created_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("now()"),
    )
    last_modified_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    @declared_attr
    def created_by_id(cls):
        return Column(
            UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        )

    @declared_attr
    def last_modified_by_id(cls):
        return Column(
            UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        )
