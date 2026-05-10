# Deploying Strands AI Agents to AWS Bedrock AgentCore Runtime

This guide walks through two approaches for deploying a Python-based [Strands](https://github.com/strands-agents/sdk-python) AI agent to [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/). Choose the approach that best fits your needs — you only need to follow one.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Approach A: SDK Integration](#approach-a-sdk-integration)
  - [Step 1: Install the SDK](#step-1-install-the-sdk)
  - [Step 2: Prepare Your Agent Code](#step-2-prepare-your-agent-code)
  - [Step 3: Test Locally](#step-3-test-locally)
  - [Step 4a: Deploy via Starter Toolkit](#step-4a-deploy-via-starter-toolkit-quick-prototyping)
  - [Step 4b: Deploy via boto3](#step-4b-deploy-via-boto3-manual-control)
- [Approach B: Custom FastAPI Agent](#approach-b-custom-fastapi-agent)
  - [Step 1: Project Setup](#step-1-project-setup)
  - [Step 2: Build the FastAPI Agent](#step-2-build-the-fastapi-agent)
  - [Step 3: Test Locally](#step-3-test-locally-1)
  - [Step 4: Containerise the Agent](#step-4-containerise-the-agent)
  - [Step 5: Push to ECR and Deploy](#step-5-push-to-ecr-and-deploy)
  - [Step 6: Invoke Your Agent](#step-6-invoke-your-agent)
- [AgentCore Runtime Requirements](#agentcore-runtime-requirements)
- [Best Practices](#best-practices)

---

## Overview

| | Approach A — SDK Integration | Approach B — Custom FastAPI Agent |
|---|---|---|
| **Best for** | Quick prototyping, simple agents | Production systems, full control |
| **Setup effort** | Minimal | Moderate |
| **HTTP server** | Automatic (provided by SDK) | Manual (you write FastAPI app) |
| **Container required** | Optional (local testing only) | Required |
| **Flexibility** | Standard | Full — custom routing, middleware, etc. |

Both approaches result in an agent deployed to AgentCore Runtime and reachable via `invoke_agent_runtime`.

---

## Prerequisites

- Python 3.10+
- AWS account with appropriate IAM permissions
- AWS CLI configured (`aws configure`)
- **Approach B only:** Docker, Finch, or Podman (container engine required)

---

## Approach A: SDK Integration

The AgentCore SDK wraps your agent function and handles the HTTP server plumbing automatically. You decorate your function and the SDK takes care of the rest.

### Step 1: Install the SDK

```bash
pip install bedrock-agentcore
```

### Step 2: Prepare Your Agent Code

The SDK follows a three-step pattern: import, initialise, decorate.

**`agent_example.py`** — synchronous (basic):
```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

app = BedrockAgentCoreApp()
agent = Agent()

@app.entrypoint
def invoke(payload):
    user_message = payload.get("prompt", "Hello")
    result = agent(user_message)
    return {"result": result.message}

if __name__ == "__main__":
    app.run()
```

**`agent_streaming.py`** — async streaming variant:
```python
from strands import Agent
from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
agent = Agent()

@app.entrypoint
async def agent_invocation(payload):
    user_message = payload.get("prompt", "No prompt provided.")
    async for event in agent.stream_async(user_message):
        yield event

if __name__ == "__main__":
    app.run()
```

> The `@app.entrypoint` decorator is what registers your function as the handler for incoming `/invocations` requests. The SDK automatically exposes the required `/ping` health check endpoint as well.

**`requirements.txt`**:
```
strands-agents
bedrock-agentcore
```

### Step 3: Test Locally

```bash
python agent_example.py
```

Then in a separate terminal:
```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world!"}'
```

The SDK serves on port `8080` by default — matching the port AgentCore Runtime expects in production.

### Step 4a: Deploy via Starter Toolkit (Quick Prototyping)

The Starter Toolkit provides a CLI that handles Docker image building, ECR pushing, and AgentCore Runtime creation in one workflow.

```bash
pip install bedrock-agentcore-starter-toolkit
```

**Expected project layout:**
```
your_project/
├── agent_example.py
├── requirements.txt
└── __init__.py
```

**Deploy:**
```bash
# Declare your entrypoint
agentcore configure --entrypoint agent_example.py

# Optional: test in a local container before pushing
agentcore launch --local

# Deploy to AWS
agentcore launch

# Invoke the deployed agent
agentcore invoke '{"prompt": "Hello"}'
```

> `agentcore launch --local` requires a running container engine. Skip it and go straight to `agentcore launch` if you don't need local container testing.

### Step 4b: Deploy via boto3 (Manual Control)

For teams who want explicit control over every deployment step.

**1. Package and push your image to ECR** (build with `linux/arm64` — see [AgentCore requirements](#agentcore-runtime-requirements)).

**2. Create the AgentCore Runtime:**
```python
import boto3

client = boto3.client('bedrock-agentcore-control', region_name="us-east-1")

response = client.create_agent_runtime(
    agentRuntimeName='hello-strands',
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': '123456789012.dkr.ecr.us-east-1.amazonaws.com/my-agent:latest'
        }
    },
    networkConfiguration={"networkMode": "PUBLIC"},
    roleArn='arn:aws:iam::123456789012:role/AgentRuntimeRole'
)
```

**3. Invoke your deployed agent:**
```python
import boto3, json

client = boto3.client('bedrock-agentcore')
payload = json.dumps({"prompt": "What is the capital of France?"}).encode()

response = client.invoke_agent_runtime(
    agentRuntimeArn='<agentRuntimeArn from creation response>',
    runtimeSessionId='<33+ character session ID>',
    payload=payload
)

print(json.loads(response['response'].read()))
```

---

## Approach B: Custom FastAPI Agent

This approach gives you full control over the HTTP layer. You write a standard FastAPI application, containerise it, push to ECR, and deploy to AgentCore Runtime. The trade-off is more initial setup.

### Step 1: Project Setup

Install `uv` (fast Python package manager):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create the project:
```bash
mkdir my-custom-agent && cd my-custom-agent
uv init --python 3.11
uv add fastapi 'uvicorn[standard]' pydantic httpx strands-agents
```

**Project layout:**
```
my-custom-agent/
├── agent.py          # FastAPI application (your agent logic lives here)
├── Dockerfile        # ARM64 container configuration
├── pyproject.toml    # Managed by uv
└── uv.lock           # Auto-generated lockfile
```

### Step 2: Build the FastAPI Agent

AgentCore Runtime requires two specific endpoints on your server:

| Endpoint | Method | Purpose |
|---|---|---|
| `/invocations` | `POST` | Receives agent requests — **required** |
| `/ping` | `GET` | Health check — **required** |

**`agent.py`:**
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime, timezone
from strands import Agent

app = FastAPI(title="Strands Agent Server", version="1.0.0")
strands_agent = Agent()

class InvocationRequest(BaseModel):
    input: Dict[str, Any]

class InvocationResponse(BaseModel):
    output: Dict[str, Any]

@app.post("/invocations", response_model=InvocationResponse)
async def invoke_agent(request: InvocationRequest):
    user_message = request.input.get("prompt", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="No 'prompt' key found in input.")

    result = strands_agent(user_message)
    return InvocationResponse(output={
        "message": result.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": "strands-agent",
    })

@app.get("/ping")
async def ping():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

> `/ping` must return a `200` for AgentCore to consider your container healthy. If this endpoint is missing or broken, your runtime will never reach a ready state.

### Step 3: Test Locally

```bash
uv run uvicorn agent:app --host 0.0.0.0 --port 8080
```

```bash
# Health check
curl http://localhost:8080/ping

# Agent invocation
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"input": {"prompt": "What is artificial intelligence?"}}'
```

### Step 4: Containerise the Agent

AgentCore Runtime runs ARM64 containers. Your `Dockerfile` must target `linux/arm64`.

**`Dockerfile`:**
```dockerfile
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache
COPY agent.py ./

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
```

Build and test locally:
```bash
# Enable multi-platform builds
docker buildx create --use

# Build ARM64 image
docker buildx build --platform linux/arm64 -t my-agent:arm64 --load .

# Run with your AWS credentials injected
docker run --platform linux/arm64 -p 8080:8080 \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  -e AWS_REGION="$AWS_REGION" \
  my-agent:arm64
```

### Step 5: Push to ECR and Deploy

```bash
REGION=us-west-2
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO=my-strands-agent

# Create the ECR repository
aws ecr create-repository --repository-name $REPO --region $REGION

# Authenticate Docker with ECR
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build and push directly to ECR
docker buildx build --platform linux/arm64 \
  -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest \
  --push .
```

Create the AgentCore Runtime (`deploy_agent.py`):
```python
import boto3

client = boto3.client('bedrock-agentcore-control')

response = client.create_agent_runtime(
    agentRuntimeName='strands_agent',
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': f'{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{REPO}:latest'
        }
    },
    networkConfiguration={"networkMode": "PUBLIC"},
    roleArn=f'arn:aws:iam::{ACCOUNT_ID}:role/AgentRuntimeRole'
)

print("Agent Runtime ARN:", response['agentRuntimeArn'])
print("Status:", response['status'])
```

```bash
uv run deploy_agent.py
```

### Step 6: Invoke Your Agent

**`invoke_agent.py`:**
```python
import boto3, json

client = boto3.client('bedrock-agentcore', region_name='us-west-2')

response = client.invoke_agent_runtime(
    agentRuntimeArn='arn:aws:bedrock-agentcore:us-west-2:<account-id>:runtime/<runtime-id>',
    runtimeSessionId='<session-id-must-be-33-or-more-characters>',
    payload=json.dumps({"input": {"prompt": "Explain machine learning simply."}}),
    qualifier="DEFAULT"
)

result = json.loads(response['response'].read())
print("Agent Response:", result)
```

```bash
uv run invoke_agent.py
```

**Example response:**
```json
{
  "output": {
    "message": {
      "role": "assistant",
      "content": [{ "text": "Machine learning is..." }]
    },
    "timestamp": "2025-07-13T01:48:06.740668+00:00",
    "model": "strands-agent"
  }
}
```

---

## AgentCore Runtime Requirements

These apply to **both approaches**:

| Requirement | Value |
|---|---|
| Container platform | `linux/arm64` |
| Required endpoints | `POST /invocations`, `GET /ping` |
| Container registry | Amazon ECR |
| Exposed port | `8080` |
| Session ID minimum length | 33 characters |
| AWS credentials | Required at runtime |

---

## Best Practices

**Development**
- Always test locally against `http://localhost:8080` before deploying — both endpoints (`/invocations` and `/ping`).
- Pin your dependency versions in `requirements.txt` or `uv.lock` for reproducible builds.

**Security**
- Follow the principle of least privilege for your `AgentRuntimeRole` IAM role.
- Never hardcode AWS credentials; use environment variables or instance roles.
- Rotate secrets regularly and avoid committing `.env` files.

**Configuration**
- Use environment variables for region, model IDs, and other tunables — avoid hardcoding them in agent code.
- Implement structured error handling in your agent handler so failures return meaningful messages rather than raw exceptions.

**Monitoring**
- Enable AWS CloudWatch logging on your AgentCore Runtime to capture invocation traces and errors.
- Consider adding structured logging (e.g. `python-json-logger`) inside your agent for easier querying.