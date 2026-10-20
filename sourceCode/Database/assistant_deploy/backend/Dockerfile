FROM python:3.11-slim
WORKDIR /app
# Install core orchestration, database, and API routing dependencies
RUN pip install fastapi uvicorn sqlalchemy aiomysql httpx
EXPOSE 8080
# Placeholder command until application code is injected
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]