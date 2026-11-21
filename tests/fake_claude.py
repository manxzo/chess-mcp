#!/usr/bin/env python3
"""A stand-in for the Claude Code CLI, driven by files in $FAKE_CLAUDE_DIR.

auth status --json   signed in iff <dir>/creds exists
auth login           prints a sign-in URL, reads a code from stdin; "good" signs in, anything else fails
auth logout          removes <dir>/creds
-p ... stream-json   records argv in args.json, every user message in messages.log; emits init on the
                     first message, then an assistant and a result line per message. <dir>/crash makes
                     it exit 3 at once; <dir>/fail_turn makes every result an error.
"""

import json
import os
import sys
from pathlib import Path

d = Path(os.environ["FAKE_CLAUDE_DIR"])
creds = d / "creds"
args = sys.argv[1:]


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def main() -> None:
    if args[:2] == ["auth", "status"]:
        signed = creds.exists()
        emit({"loggedIn": signed, "authMethod": "claude.ai" if signed else "none", "email": "me@example.test" if signed else None})
    elif args[:2] == ["auth", "login"]:
        print("Opening browser to sign in…")
        print("If the browser didn't open, visit: https://auth.example.test/oauth?state=abc", flush=True)
        print("Paste code here if prompted > ", end="", flush=True)
        code = sys.stdin.readline().strip()
        if code != "good":
            print("Invalid authorization code")
            sys.exit(1)
        creds.write_text("ok")
        print("Signed in")
    elif args[:2] == ["auth", "logout"]:
        creds.unlink(missing_ok=True)
    elif args[:1] == ["-p"]:
        (d / "args.json").write_text(json.dumps(args))
        if (d / "crash").exists():
            print("boom: cannot start", file=sys.stderr, flush=True)
            sys.exit(3)
        model = args[args.index("--model") + 1]
        first = True
        for line in sys.stdin:
            text = json.loads(line)["message"]["content"]
            with (d / "messages.log").open("a") as fh:
                fh.write(text + "\n")
            if first:
                emit({"type": "system", "subtype": "init", "model": model})
                first = False
            emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})
            err = (d / "fail_turn").exists()
            emit({"type": "result", "subtype": "error_during_execution" if err else "success", "is_error": err, "result": "rate limited" if err else "done"})
    else:
        sys.exit(2)


main()
