from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import payments, analytics, leads

app = FastAPI(title="Homnivas Finance Pro API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(payments.router)
app.include_router(analytics.router)
app.include_router(leads.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
