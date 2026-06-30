import asyncio
import os
from models.database import init_db, engine
from models.base import Base
# Import all models to ensure they are registered with Base.metadata
from models.product_moderation import ProductModeration
from models.product_blocking_reasons import ProductBlockingReason
from models.product_moderation_field_report import ProductModerationFieldReport

async def run_init():
    print("Iniciando criação das tabelas no banco de dados...")
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./neomarket_moderation.db")
    print(f"DATABASE_URL: {db_url}")
    
    try:
        await init_db()
        print("✅ Tabelas criadas com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao criar tabelas: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_init())
