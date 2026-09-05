from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_analytics, routes_decisions, routes_portfolio, routes_sync
from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Джарвис", docs_url="/api/docs", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_portfolio.router)
app.include_router(routes_sync.router)
app.include_router(routes_decisions.router)
app.include_router(routes_analytics.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
