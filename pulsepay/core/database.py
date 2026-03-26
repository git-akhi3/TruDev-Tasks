from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import (
	AsyncAttrs,
	AsyncEngine,
	AsyncSession,
	async_sessionmaker,
	create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class UUIDPrimaryKeyMixin:
	id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		primary_key=True,
		server_default=text("gen_random_uuid()"),
	)


class TimestampMixin:
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=text("timezone('utc', now())"),
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=text("timezone('utc', now())"),
		server_onupdate=text("timezone('utc', now())"),
	)


class Base(UUIDPrimaryKeyMixin, TimestampMixin, AsyncAttrs, DeclarativeBase):
	pass


def _database_url() -> str:
	url = settings().DATABASE_URL
	if not url.startswith("postgresql+asyncpg://"):
		raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver.")
	return url


engine: AsyncEngine = create_async_engine(
	_database_url(),
	pool_pre_ping=True,
	pool_size=settings().DB_POOL_SIZE,
	max_overflow=settings().DB_MAX_OVERFLOW,
	pool_timeout=settings().DB_POOL_TIMEOUT_SECONDS,
	pool_recycle=settings().DB_POOL_RECYCLE_SECONDS,
)

SessionLocal = async_sessionmaker(
	bind=engine,
	class_=AsyncSession,
	expire_on_commit=False,
	autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
	async with SessionLocal() as session:
		yield session
