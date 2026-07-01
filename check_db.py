import asyncio
from sqlalchemy import select
from models.database import async_session_factory
from models.product_moderation import ProductModeration

async def check():
    async with async_session_factory() as session:
        result = await session.execute(select(ProductModeration))
        records = result.scalars().all()
        print(f"Total de registros encontrados: {len(records)}")
        for rec in records:
            print(f"- ID: {rec.id}, Product: {rec.product_id}, Status: {rec.status}")

if __name__ == "__main__":
    asyncio.run(check())
