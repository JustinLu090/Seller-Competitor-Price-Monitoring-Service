from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import alerts, auth, products

app = FastAPI(title="Price Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(alerts.router)


@app.get("/health")
def health():
    return {"status": "ok"}
