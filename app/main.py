"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import create_tables
from app.routers import auth, devices, readings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine for a single-node portfolio service. A deployment with more than one
    # instance would run migrations (Alembic) instead of creating on startup.
    create_tables()
    yield


app = FastAPI(
    title="IoT Telemetry API",
    description=(
        "Ingests sensor readings from field devices and serves them back to "
        "operators. Devices authenticate with an API key and may only write; "
        "users authenticate with a JWT and may only read, unless they are admin."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(readings.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
