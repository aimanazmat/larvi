"""
Test the Email Agent + Calendar Agent tool layer WITHOUT calling Claude/
Anthropic at all. This proves the tools, mock data, and multi-step data
flow (Workflow 3: email -> calendar) all work correctly, with zero API
cost and zero API key needed.

The Master Agent's job (understanding natural language, deciding which
tool to call) normally comes from Claude — that part is skipped here.
Instead we call the tools directly, the way the Master Agent WOULD have
called them after understanding a request.

Usage: python scripts/test_tools_no_llm.py
"""
import sys
sys.path.insert(0, ".")

from app.tools import email_tools, calendar_tools  # noqa: E402


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------
section("WORKFLOW 1: Find an email from a specific sender (Email Agent)")
# ---------------------------------------------------------------------
result = email_tools.search_emails(sender="ahmed")
print("search_emails(sender='ahmed') ->", result)
assert result["success"], "search_emails failed"
assert result["data"]["count"] >= 1, "Expected at least 1 email from ahmed"
print(f"FOUND: '{result['data']['emails'][0]['subject']}' from {result['data']['emails'][0]['from']}")


# ---------------------------------------------------------------------
section("WORKFLOW 2: Calendar lookup + reschedule (Calendar Agent)")
# ---------------------------------------------------------------------
events = calendar_tools.get_events()
print("get_events() ->", events)
assert events["success"]
first_event = events["data"]["events"][0]
print(f"FOUND EVENT: '{first_event['title']}' (id={first_event['id']})")

updated = calendar_tools.update_event(event_id=first_event["id"], start="2026-08-20T18:00:00",
                                       end="2026-08-20T19:00:00")
print("update_event(reschedule to 6PM) ->", updated)
assert updated["success"]
print(f"RESCHEDULED: '{updated['data']['title']}' now starts at {updated['data']['start']}")


# ---------------------------------------------------------------------
section("WORKFLOW 3: Multi-agent — email details -> calendar event")
# ---------------------------------------------------------------------
# Step 1: Email Agent finds the email
found = email_tools.search_emails(sender="ahmed", subject_contains="meeting")
print("1) email_tools.search_emails ->", found)
assert found["success"] and found["data"]["count"] >= 1

email_id = found["data"]["emails"][0]["id"]

# Step 2: Email Agent reads full content
full_email = email_tools.read_email(email_id)
print("2) email_tools.read_email ->", full_email)
assert full_email["success"]
print(f"   Email body: {full_email['data']['body'][:80]}...")

# Step 3: (In real Larvi, Claude would extract "tomorrow 3 PM" from the body.
#          Here we hardcode the extracted time to prove the calendar side works.)
meeting_start = "2026-08-20T15:00:00"
meeting_end = "2026-08-20T16:00:00"

# Step 4: Calendar Agent checks availability
avail = calendar_tools.check_availability(start=meeting_start, end=meeting_end)
print("3) calendar_tools.check_availability ->", avail)
assert avail["success"]

# Step 5: Calendar Agent creates the event (only if free)
if avail["data"]["available"]:
    created = calendar_tools.create_event(
        title="Project Meeting (from Ahmed's email)",
        start=meeting_start,
        end=meeting_end,
        attendees=["ahmed@example.com"],
    )
    print("4) calendar_tools.create_event ->", created)
    assert created["success"]
    print(f"   CREATED EVENT: '{created['data']['title']}' at {created['data']['start']}")
else:
    print("   Not free at that time — would report conflict to user instead of creating.")


# ---------------------------------------------------------------------
section("WORKFLOW 4: Safety — send_email tool (would be confirmation-gated by Master Agent)")
# ---------------------------------------------------------------------
sent = email_tools.send_email(to="ali@example.com", subject="Project Update",
                               body="Hi Ali, the project update is ready for review.")
print("email_tools.send_email ->", sent)
assert sent["success"]
print(f"   SENT: message_id={sent['data']['message_id']}")
print("   (In the real app, Master Agent would have asked 'Should I send this? yes/no'")
print("    BEFORE calling this tool — see app/master_agent.py SENSITIVE_TOOLS.)")


# ---------------------------------------------------------------------
section("ERROR HANDLING: looking up something that doesn't exist")
# ---------------------------------------------------------------------
missing = email_tools.read_email("email-does-not-exist")
print("read_email('email-does-not-exist') ->", missing)
assert not missing["success"]
print(f"   Correctly returned success=False, error='{missing['error']}'")

print("\n" + "=" * 70)
print("ALL TOOL-LAYER TESTS PASSED — Email Agent, Calendar Agent, and the")
print("multi-step email->calendar workflow all work correctly.")
print("(This ran with zero Anthropic API calls / zero cost.)")
print("=" * 70)
