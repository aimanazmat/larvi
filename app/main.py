"""
Larvi API server.

Run with:  uvicorn app.main:app --reload
Then POST to /chat with {"session_id": "...", "message": "..."}.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.schemas import ChatRequest, ChatResponse
from app.core.context import ContextStore
from app.config import settings

if settings.llm_backend == "ollama":
    from app import master_agent_ollama as master_agent
else:
    from app import master_agent

app = FastAPI(title="Larvi", description="Autonomous Email & Calendar AI Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "mock_mode": settings.mock_mode}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        return master_agent.handle_message(req.session_id, req.message, req.confirm)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/{session_id}/reset")
def reset_session(session_id: str):
    ContextStore.reset(session_id)
    return {"status": "reset", "session_id": session_id}
