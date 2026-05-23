from fastapi import FastAPI
from backend.api.routes import router

app = FastAPI(title="Astra API", version="1.0.0")
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
