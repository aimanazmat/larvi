"""
Converts Larvi's tool schemas (originally written in Claude's
`input_schema` format) into the OpenAI-style `function` format that
Ollama's tool-calling API expects. Both agents' schemas
(app/agents/email_agent.py, calendar_agent.py) stay as the single
source of truth — this module just reshapes them for Ollama.
"""
from app.agents import email_agent, calendar_agent


def _to_ollama_tool(claude_tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": claude_tool["name"],
            "description": claude_tool["description"],
            "parameters": claude_tool["input_schema"],
        },
    }


def get_ollama_tools() -> list[dict]:
    claude_tools = email_agent.TOOL_SCHEMAS + calendar_agent.TOOL_SCHEMAS
    return [_to_ollama_tool(t) for t in claude_tools]
