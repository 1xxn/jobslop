"""Attrappe für die `claude`-CLI. Verhalten über FAKE_CLAUDE_MODE, Mitschnitt nach FAKE_CLAUDE_LOG."""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")

if args[:1] == ["--version"]:
    print("2.1.310 (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(
        json.dumps(
            {
                "loggedIn": mode != "logged_out",
                "authMethod": "api_key" if mode == "api_key" else "claude.ai",
                "email": "max.mustermann@example.com",
                "subscriptionType": "pro",
            }
        )
    )
    sys.exit(0 if mode != "logged_out" else 1)


def opt(name: str) -> str:
    return args[args.index(name) + 1]


record = {
    "args": args,
    "stdin": sys.stdin.buffer.read().decode("utf-8"),  # wie Claude Code: UTF-8, auch unter Windows
    "cwd": os.getcwd(),
    "files": sorted(os.listdir(".")),
    "api_key_seen": "ANTHROPIC_API_KEY" in os.environ,
    "system": Path(opt("--system-prompt-file")).read_text(encoding="utf-8"),
}
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\n")

if mode == "limit":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "You've hit your session limit · resets 5pm (Europe/Berlin)",
            }
        )
    )
    sys.exit(1)
if mode == "auth":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "Invalid API key · Please run /login",
            }
        )
    )
    sys.exit(1)
if mode == "crash":
    print("Segmentation fault", file=sys.stderr)
    sys.exit(139)
if mode == "text_only":  # ältere Versionen: JSON steckt im result-Text
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": os.environ.get("FAKE_CLAUDE_OUTPUT", "{}"),
            }
        )
    )
    sys.exit(0)

print("Lade Einstellungen …")  # Rauschen vor dem JSON darf nicht stören
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "",
            "structured_output": json.loads(os.environ.get("FAKE_CLAUDE_OUTPUT", "{}")),
            "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
        }
    )
)
