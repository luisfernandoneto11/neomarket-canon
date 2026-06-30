import uvicorn
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apis.moderation.events import router as events_router
from models.database import init_db, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    print("Iniciando servidor e verificando banco de dados...")
    try:
        await init_db()
        print("Banco de dados verificado/inicializado.")
    except Exception as e:
        print(f"Aviso na inicialização do DB: {e}")
    
    yield
    
    # Shutdown: Close connections
    print("Encerrando servidor...")
    await engine.dispose()

app = FastAPI(
    title="NeoMarket Moderation Service",
    lifespan=lifespan
)

# Include routers
app.include_router(events_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
