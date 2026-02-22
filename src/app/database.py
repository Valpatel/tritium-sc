"""Database setup and session management."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

# Async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency for getting database sessions."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create FTS5 virtual tables if they don't exist
    async with async_session() as session:
        await session.execute(
            text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                    description, event_type, content=events, content_rowid=id
                )
            """)
        )
        await session.execute(
            text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
                    text, content=transcripts, content_rowid=id
                )
            """)
        )
        await session.commit()
