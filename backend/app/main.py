from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_portfolio, routes_sync

app = FastAPI(title="Джарвис", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_portfolio.router)
app.include_router(routes_sync.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
