import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.ollama import OllamaModel

app = BedrockAgentCoreApp()
agent = Agent()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5")

model = OllamaModel(model_id=MODEL_NAME, host=OLLAMA_BASE_URL)

strands_agent = Agent(model=model)

@app.entrypoint
async def invoke(payload):
    user_message = payload.get("message")
    stream = agent.stream_async(user_message)
    async for chunk in stream:
        print(chunk)
        yield chunk

if __name__ == '__main__':
    app.run()