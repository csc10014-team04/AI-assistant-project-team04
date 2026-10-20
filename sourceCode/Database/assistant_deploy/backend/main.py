from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, text

DATABASE_URL = "mysql+aiomysql://root:secure_root_hash_2026@db:3306/assistant_db"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

app = FastAPI(title="University Life Assistant API")

# Asynchronous Generator Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

@app.get("/health")
async def health_check():
    return {"status": "operational", "layer": "orchestration"}

@app.get("/db_test")
async def test_db_connection(db: AsyncSession = Depends(get_db)):
    try:
        # Execute a raw SQL test query
        result = await db.execute(text("SELECT VERSION()"))
        version = result.scalar()
        return {"status": "connected", "mysql_version": version}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))