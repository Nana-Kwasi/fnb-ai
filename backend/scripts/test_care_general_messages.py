"""Run care engine with general messages and print responses. No server needed.
Usage: cd backend && PYTHONPATH=. python scripts/test_care_general_messages.py
"""
from app.services.care_engine import _rule_based_reply

ctx = {"has_customer": True}
history = []
chunks = []

messages = [
    "hello",
    "hi there",
    "good morning",
    "what can you do",
    "help",
    "thanks",
    "bye",
    "I want to speak to someone",
]

print("Care model – general message test\n" + "-" * 50)
for msg in messages:
    reply, intent, actions, escalate = _rule_based_reply(msg, ctx, history, chunks)
    print(f"User:  {msg}")
    print(f"Bot:   {reply[:200]}{'...' if len(reply) > 200 else ''}")
    print(f"Intent: {intent}  escalate: {escalate}\n")
