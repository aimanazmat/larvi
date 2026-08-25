"""
Demo script for Larvi running on Ollama (free, local model — no API key,
no billing, no Anthropic dependency).

Prerequisites:
    1. Install Ollama: https://ollama.com/download
    2. Pull a tool-calling-capable model:
         ollama pull llama3.1
    3. Ollama server must be running (it auto-starts after install, or
       run `ollama serve` in a separate terminal).

Usage:
    python scripts/demo_ollama.py            # scripted multi-step workflow demos
    python scripts/demo_ollama.py --chat      # interactive REPL
"""
import sys
import uuid

sys.path.insert(0, ".")

from app import master_agent_ollama as master_agent  # noqa: E402


def run_turn(session_id: str, message: str, confirm=None):
    print(f"\n>>> USER: {message}" + (f"  [confirm={confirm}]" if confirm is not None else ""))
    resp = master_agent.handle_message(session_id, message, confirm)
    print(f"LARVI: {resp.reply}")
    if resp.workflow_trace:
        print("  trace:")
        for step in resp.workflow_trace:
            print(f"    - {step}")
    if resp.tool_calls:
        for tc in resp.tool_calls:
            status = "OK" if tc.success else f"FAILED ({tc.error})"
            print(f"  tool: {tc.tool_name}({tc.tool_input}) -> {status}")
    return resp


def demo_workflow_1_email_lookup():
    print("\n" + "=" * 70)
    print("WORKFLOW 1: Find an email from a specific sender")
    print("=" * 70)
    sid = f"demo1-{uuid.uuid4().hex[:6]}"
    run_turn(sid, "Find the email from Ahmed about the project meeting.")


def demo_workflow_2_context_followup():
    print("\n" + "=" * 70)
    print("WORKFLOW 2: Calendar lookup + context-based follow-up (reschedule)")
    print("=" * 70)
    sid = f"demo2-{uuid.uuid4().hex[:6]}"
    run_turn(sid, "What meetings do I have coming up?")
    run_turn(sid, "Move the Weekly Sync to 6 PM today instead.")


def demo_workflow_3_multi_agent_email_to_calendar():
    print("\n" + "=" * 70)
    print("WORKFLOW 3: Find meeting details in email, check availability, add to calendar")
    print("=" * 70)
    sid = f"demo3-{uuid.uuid4().hex[:6]}"
    run_turn(
        sid,
        "Check whether I received an email from Ahmed about tomorrow's project meeting. "
        "If you find the meeting time, check whether I'm free and add it to my calendar.",
    )


def demo_workflow_4_confirmation_gated_send():
    print("\n" + "=" * 70)
    print("WORKFLOW 4: Sending an email requires explicit confirmation")
    print("=" * 70)
    sid = f"demo4-{uuid.uuid4().hex[:6]}"
    resp = run_turn(sid, "Send Ali an email letting him know the project update is ready for review.")
    if resp.pending_confirmation:
        run_turn(sid, "yes, send it", confirm=True)


def interactive():
    sid = f"chat-{uuid.uuid4().hex[:6]}"
    print(f"Larvi (Ollama) interactive session ({sid}). Type 'exit' to quit.")
    pending = False
    while True:
        msg = input("\nyou> ").strip()
        if msg.lower() in ("exit", "quit"):
            break
        confirm = None
        if pending:
            if msg.lower() in ("yes", "y", "confirm"):
                confirm = True
            elif msg.lower() in ("no", "n", "cancel"):
                confirm = False
        resp = master_agent.handle_message(sid, msg, confirm)
        print(f"larvi> {resp.reply}")
        pending = resp.pending_confirmation is not None


if __name__ == "__main__":
    if "--chat" in sys.argv:
        interactive()
    else:
        demo_workflow_1_email_lookup()
        demo_workflow_2_context_followup()
        demo_workflow_3_multi_agent_email_to_calendar()
        demo_workflow_4_confirmation_gated_send()
