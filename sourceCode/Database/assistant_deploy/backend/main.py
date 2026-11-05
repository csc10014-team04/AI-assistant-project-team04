from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, text

import os
DATABASE_URL = os.environ["DATABASE_URL"]  # no hard-coded credentials; injected by docker-compose from .env


engine = create_async_engine(DATABASE_URL, echo=False)  # echo=True would log schedule data
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
        raise HTTPException(status_code=500, detail="database unreachable")

from pydantic import BaseModel
import httpx

from pydantic import Field

class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)

# Định tuyến AI Engine: 'local_llama_inference' phân giải qua internal_bridge của Docker trên cổng 8000
VLLM_API_BASE = "http://local_llama_inference:8000/v1"

@app.get("/ai_test")
async def test_ai_connection():
    try:
        # Thăm dò endpoint mô hình tương thích OpenAI của vLLM
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{VLLM_API_BASE}/models", timeout=5.0)
            response.raise_for_status()
            return {"status": "connected", "ai_engine": "vLLM", "data": response.json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail="AI engine unreachable")

@app.post("/chat")
async def chat_with_llama(request: PromptRequest):
    try:
        # Trích xuất mô hình động và thực thi suy luận
        async with httpx.AsyncClient() as client:
            model_res = await client.get(f"{VLLM_API_BASE}/models", timeout=5.0)
            model_id = model_res.json()["data"][0]["id"]
            
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": request.prompt}],
                "max_tokens": 150
            }
            response = await client.post(f"{VLLM_API_BASE}/chat/completions", json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail="AI engine error")