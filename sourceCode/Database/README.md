Backend Integration Guide - Virtual Assistant (CSC10014)

This is the System Integration phase. The core infrastructure (Database, AI Engine, and Backend Gateway) is currently hosted centrally on the Team Lead's laptop.

Central Host IP: 192.168.100.112

This guide outlines how to connect your local development environment to the central host, access the database, and route data to the local Llama 3.1 AI Engine.

1. Database Access & Connection

The project uses MySQL 8.0. You will interact with it in two ways: externally (via a DB Client like DBeaver) for schema management, and internally (via Python) for the application logic.

A. External Access (GUI Client)

Use these credentials to connect your local database client (DBeaver, MySQL Workbench, DataGrip) to the central host to view tables and insert mock data:

Host: 192.168.100.112

Port: 3306

Database: university_assistant

Username: schedule_admin

Password: (Get the .env password from the Host Lead via team's Discord or Zalo)

B. Connecting the Data Line (Python/SQLAlchemy)

When writing backend code (FastAPI), your service will run inside the Docker network. Therefore, you must use the internal Docker DNS name (db), not the Host IP, to connect.

1. Install Dependencies:

pip install fastapi sqlalchemy aiomysql


2. Database Connection Setup (database.py):

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# NOTE: Use 'db:3306' because the backend container communicates internally via Docker bridge.
DATABASE_URL = "mysql+aiomysql://schedule_admin:[PASSWORD]@db:3306/university_assistant"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


2. Calling the AI Engine (vLLM)

The Llama 3.1 model is served via vLLM. Like the database, the backend communicates with the AI engine internally through the Docker network.

Internal AI Endpoint: http://llama_engine:8000/v1/chat/completions

Example Integration (FastAPI Route)

Here is how to fetch data from the database, construct a prompt, and call the AI engine using httpx.

1. Install HTTP client:

pip install httpx


2. API Route Implementation (main.py):

from fastapi import FastAPI, Depends, HTTPException
import httpx
from database import get_db

app = FastAPI()

VLLM_ENDPOINT = "http://llama_engine:8000/v1/chat/completions"
MODEL_NAME = "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"

@app.post("/api/v1/assistant/chat")
async def chat_with_assistant(user_message: str, db=Depends(get_db)):
    # 1. (Optional) Query the DB for student schedule/info here
    # context = await db.execute(...)

    # 2. Construct the OpenAI-compatible payload
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a helpful university assistant. Use the provided context to answer questions."},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 512,
        "temperature": 0.3
    }

    # 3. Call the local AI Engine
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(VLLM_ENDPOINT, json=payload, timeout=60.0)
            response.raise_for_status()
            ai_data = response.json()
            
            return {
                "status": "success", 
                "reply": ai_data["choices"][0]["message"]["content"]
            }
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"AI Engine unreachable: {exc}")


3. Testing Your Endpoints

When you push your FastAPI code to the host and the container is running, you can test your endpoints from your own machine using Postman or cURL.

Since you are calling the Backend from the outside, you use the Host IP and the exposed Backend Port (8080).

cURL Example:

curl -X POST "http://192.168.100.112:8080/api/v1/assistant/chat" \
     -H "Content-Type: application/json" \
     -d '{"user_message": "What is my schedule for today?"}'


*Important Rules for Backend Devs

Never expose the AI Engine directly to the Frontend. The Backend must act as the middleman to inject Database context.

If the AI times out, notify the Host Lead. The local GPU may be overloaded and require a VRAM flush.

Keep your system prompts concise. We are constrained by a strict 2048 maximum context length due to VRAM limitations.