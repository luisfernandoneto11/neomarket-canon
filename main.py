from fastapi import FastAPI
from apis.moderation.events import router as moderation_router
from apis.b2b import b2b_router
from apis.b2b.products import router as products_router
from models.database import engine, Base

app = FastAPI(
    title="NeoMarket Moderation Service",
    description="Serviço de moderação de eventos de produto",
    version="1.0.0"
)

# Incluir o roteador de moderação
app.include_router(moderation_router)

# Incluir o roteador B2B
app.include_router(b2b_router)

# Incluir o roteador de Produtos
app.include_router(products_router)

@app.on_event("startup")
async def startup():
    """Cria as tabelas no banco de dados ao iniciar"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {"status": "ok", "service": "moderation"}