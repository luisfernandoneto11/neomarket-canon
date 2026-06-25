from fastapi import FastAPI
from apis.moderation.events import router as moderation_router
from apis.b2b import b2b_router
from apis.b2b.products import router as products_router
from apis.b2b.catalog import router as catalog_router
from apis.b2b.reserve import router as reserve_router
from apis.b2b.moderation_events import router as moderation_events_router
from apis.b2c.router import router as b2c_router
from apis.b2c.product_card import router as product_card_router
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

# Incluir o roteador do Catálogo
app.include_router(catalog_router)

# Incluir oroteador de Reserva
app.include_router(reserve_router)

# Incluir o roteador de Eventos de Moderação
app.include_router(moderation_events_router)

# Incluir o roteador B2C
app.include_router(b2c_router)

# Incluir o roteador de Product Card (B2C)
app.include_router(product_card_router)

@app.on_event("startup")
async def startup():
    """Cria as tabelas no banco de dados ao iniciar"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {"status": "ok", "service": "moderation"}