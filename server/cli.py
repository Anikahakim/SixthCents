"""Talk to the agent in the terminal (plain text, no voice). Run: python cli.py"""
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import agent  # noqa: E402
import store  # noqa: E402

store.init()

if __name__ == "__main__":
    session_id = None
    print("SixthCents text mode. Type a request, or 'quit'.\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        if not text:
            continue
        result = agent.chat(session_id, text)
        session_id = result["session_id"]
        print(f"\nagent> {result['reply']}\n")
        pending = result["pending_confirmation"]
        if pending:
            print(f"  [pending confirmation: {pending['title']} / size {pending['size']} / "
                  f"${pending['total']:.2f}. Payment is not wired up yet (step 4/5).]\n")
