import os
from urllib.parse import quote_plus, urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "CHIRAAG Routing Engine"
    API_V1_STR: str = "/api/v1"

    # PostgreSQL / PostGIS Connection Settings
    POSTGRES_USER: str = "chiraag"
    POSTGRES_PASSWORD: str = "chiraag"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5434"
    POSTGRES_DB: str = "chiraag"

    # Managed providers require TLS. "prefer" negotiates it when offered and
    # falls back for the local container, which has no certificate.
    POSTGRES_SSLMODE: str = "prefer"

    # Set this to a full connection string to bypass the parts above. Handy
    # when a host hands you one DSN rather than five separate values.
    #
    # A plain DATABASE_URL environment variable is honoured too. That is the
    # name Render sets by convention, and the one you reach for after copying
    # a URI out of the Supabase dashboard. Without that fallback, pasting the
    # connection string into the obvious variable does nothing at all and the
    # service quietly dials localhost:5434 instead.
    DATABASE_URL_OVERRIDE: str = ""

    # Comma-separated origins allowed to call the API. Set to the deployed
    # frontend URL in production.
    ALLOWED_ORIGINS_RAW: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def DATABASE_URL(self) -> str:
        dsn = self.DATABASE_URL_OVERRIDE or os.getenv("DATABASE_URL", "")

        if dsn:
            # SQLAlchemy dropped the "postgres://" alias years ago; Supabase
            # and several hosts still hand one out. Left unfixed this raises
            # NoSuchModuleError at engine creation.
            if dsn.startswith("postgres://"):
                dsn = "postgresql://" + dsn[len("postgres://"):]

            return dsn

        # Managed database passwords routinely contain characters that are
        # reserved in a URL (@ : / ? #). Without quoting, the DSN silently
        # parses into the wrong host or user.
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)

        return (
            f"postgresql://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSLMODE}"
        )

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        # Trailing slashes are stripped because an Origin header never carries
        # one: "https://chiraag.vercel.app/" in the environment variable would
        # never match and every browser call would fail CORS.
        return [
            origin.strip().rstrip("/")
            for origin in self.ALLOWED_ORIGINS_RAW.split(",")
            if origin.strip()
        ]

    @property
    def _db_parts(self):
        try:
            return urlsplit(self.DATABASE_URL)
        except ValueError:
            return None

    @property
    def database_summary(self) -> str:
        """host:port/dbname, with no credentials. Safe to log."""
        parts = self._db_parts

        if parts is None or not parts.hostname:
            return "unparseable connection string"

        try:
            port = parts.port or 5432
        except ValueError:
            port = "?"

        name = (parts.path or "").lstrip("/") or "?"

        return f"{parts.hostname}:{port}/{name}"

    @property
    def uses_supabase_direct_host(self) -> bool:
        """
        True for db.<project-ref>.supabase.co -- Supabase's *direct* endpoint.

        That hostname resolves to IPv6 only. Render has no outbound IPv6, so
        the connection times out in a way that reads like "the database is
        down" rather than "you picked the wrong host". The session and
        transaction poolers (...pooler.supabase.com) are reachable over IPv4.
        """
        parts = self._db_parts
        host = (parts.hostname or "") if parts is not None else ""

        return host.startswith("db.") and host.endswith(".supabase.co")


settings = Settings()
