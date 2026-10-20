from fastapi import FastAPI

app = FastAPI(title="University Life Assistant API")

@app.get("/health")
async def health_check():
    return {"status": "operational", "layer": "orchestration"}
