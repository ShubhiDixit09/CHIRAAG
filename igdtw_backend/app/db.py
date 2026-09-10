from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# create_engine() does not open a connection -- the first one is established
# lazily, on first use. That is what lets app.main import and start serving
# while the database is unreachable.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Automatically re-connects dropped connections
    pool_size=5,
    max_overflow=5,
    # Supabase's pooler closes idle connections server-side. Recycling inside
    # that window stops the app handing out a socket the other end has already
    # hung up on, which surfaces as a random failed request after a quiet spell.
    pool_recycle=300,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI Dependency for database session management."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
