FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx
COPY status_server.py .
EXPOSE 80
CMD ["uvicorn", "status_server:app", "--host", "0.0.0.0", "--port", "80"]
