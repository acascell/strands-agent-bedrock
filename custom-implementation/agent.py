from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime, timezone
from strands import Agent
from strands.models.ollama import OllamaModel
import os

app = FastAPI(title="Strands Agent Server", version="1.0.0")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5")

model = OllamaModel(model_id=MODEL_NAME, host=OLLAMA_BASE_URL)

strands_agent = Agent(model=model)

class InvocationRequest(BaseModel):
    input: Dict[str, Any]

class InvocationResponse(BaseModel):
    output: Dict[str, Any]


@app.post(
    "/invocations",
    response_model=InvocationResponse)
async def invoke_agent(request: InvocationRequest):
    try:
        user_message = request.input.get("prompt", "")
        if not user_message:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: prompt"
            )

        result = strands_agent(user_message)
        response = {
            "message": result.message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return InvocationResponse(output=response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/ping")
async def ping():
    return {"status": "ok"}

if __name__  == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
