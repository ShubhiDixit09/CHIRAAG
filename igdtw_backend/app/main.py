import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import Base, engine
from app.routers import route_router, evidence_router

# uvicorn owns logging configuration everywhere this runs, so borrowing its
# logger is what makes these lines actually show up in the Render log stream.
# A fresh logging.getLogger(__name__) has no handler attached and would be
# swallowed below WARNING.
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup work that touches the network, kept out of module import.

    create_all() opens a connection. Running it at import time means an
    unreachable database -- a paused Supabase project, a cold pooler, a
    transient DNS blip -- kills the process before it can serve anything, and
    the platform restarts it straight back into the same failure. Doing it
    here, guarded, lets the API come up and report the problem instead of
    disappearing.
    """
    logger.info("CHIRAAG starting -- database: %s", settings.database_summary)

    if settings.uses_supabase_direct_host:
        logger.warning(
            "Database host is Supabase's direct endpoint, which resolves to "
            "IPv6 only. Hosts without outbound IPv6 (Render included) cannot "
            "reach it -- switch to the pooler host if connections time out."
        )

    if settings.ALLOWED_ORIGINS:
        logger.info("CORS origins: %s", ", ".join(settings.ALLOWED_ORIGINS))
    else:
        logger.warning(
            "ALLOWED_ORIGINS_RAW is empty -- every browser request will be "
            "blocked by CORS."
        )

    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database reachable, schema verified.")
    except Exception as exc:
        logger.error(
            "Could not reach the database at startup (%s). The API is up; "
            "routing and evidence requests will fail until it recovers. "
            "Check /health/db for the current state.",
            exc.__class__.__name__,
        )

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Safety-focused navigation API minimizing exposure to unlit road segments.",
    version="0.1.0",
    lifespan=lifespan,
)

# Restricted to the configured frontend origins. A wildcard combined with
# allow_credentials=True is rejected by browsers anyway, and this API sends
# no cookies or auth headers, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Include routers
app.include_router(route_router)
app.include_router(evidence_router)


@app.get("/", tags=["Health"])
def health_check():
    """
    Liveness only.

    This deliberately does not touch the database. It is the endpoint the
    hosting platform polls, and failing it while Postgres is briefly away
    would have the platform restart a process that is otherwise healthy --
    which is the crash loop this file exists to avoid.
    """
    return {
        "status": "online",
        "system": settings.PROJECT_NAME,
        "docs_url": "/docs"
    }


@app.get("/health/db", tags=["Health"])
def health_db():
    """
    Readiness. Use this to tell "the API is down" from "the database is away".
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Class name only. The exception text carries the DSN, including host,
        # username and password.
        raise HTTPException(
            status_code=503,
            detail=f"Database unreachable ({exc.__class__.__name__})",
        )

    return {"database": "reachable", "target": settings.database_summary}
