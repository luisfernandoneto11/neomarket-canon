import uvicorn
from fastapi import FastAPI
from apis.moderation.events import router as events_router
from models.database import init_db

app = FastAPI(title="NeoMarket Moderation Service")

# Include routers
app.include_router(events_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    # Initialize database tables
    # Note: In a real production environment, we would use migrations (Alembic)
    # For this check, we'll try to initialize the DB.
    # We use a try-except because the default DATABASE_URL might not be accessible
    try:
        await init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        print("Continuing without database initialization (using existing DB or mock)")

if __name__ == "__main__":
    uvicorn.run("main.py:app", host="0.0.0.0", port=8000, reload=False)
