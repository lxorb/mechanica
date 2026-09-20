"""Create or update the ElevenLabs agent that reads this manual out loud, and its five tools.

    api/.venv/Scripts/python tools/elevenlabs_setup.py --dry-run   # print every request body, no network
    api/.venv/Scripts/python tools/elevenlabs_setup.py             # create or update; prints the agent id
    api/.venv/Scripts/python tools/elevenlabs_setup.py --delete    # remove the agent and its tools

Then put the printed id in ELEVENLABS_AGENT_ID (API process and Worker) so /voice/config serves it
and /voice/elevenlabs/session can mint a credential for it.

Needs ELEVENLABS_API_KEY, or C:\\Users\\me\\agent-secrets\\elevenlabs.txt, and a PUBLIC_BASE that
ElevenLabs' servers can actually reach over https — they call the four webhook tools directly, so
an http://localhost base produces an agent that can never read anything.

This is the ElevenLabs sibling of api/app/voice.py's `_functions()`, and it differs from it in the
two ways the two platforms differ:

  * Deepgram is told its tools inline, per session. ElevenLabs tools are workspace objects with
    their own ids, created once and referenced by the agent, so this script is idempotent by name:
    it lists /v1/convai/tools, PATCHes the ones it already owns and POSTs the rest.
  * Deepgram puts the manual id in the endpoint's query string. Here it goes into the URL *and*
    the X-Manual-Id header *and* the body schema, all three from the {{manual_id}} dynamic
    variable, because which of those an account substitutes is not verifiable from this repo -
    app/voice_elevenlabs.py resolves them header-first and ignores an unsubstituted placeholder.

--dry-run is the reviewable artefact: it prints the exact JSON that would be POSTed, so the wiring
can be read (and diffed) before anyone pays for a key.

Reference: elevenlabs.io/docs/api-reference/tools/create, .../agents/create,
.../agents-platform/customization/tools/{server-tools,client-tools}.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import voice_elevenlabs as el  # noqa: E402
from app.config import settings  # noqa: E402

API = "https://api.elevenlabs.io"
NAME = "Mechanica - trust the manual"
TAG = "trustthemanual"

# The four grounded tools, in the order the agent is told to reach for them. Each entry is
# (name, description, {arg: (json type, description)}, [required args]). `manualId` is NOT in here:
# it is bound by the URL and the header, never by the model. See the module docstring.
WEBHOOKS = [
    (
        "find_procedure",
        "Find which chapters and printed pages of this manual cover a job or a topic. Call this first, every turn.",
        {"query": ("string", "What the mechanic asked, in their own words.")},
        ["query"],
    ),
    (
        "read_page",
        "The verbatim printed text of one page of this manual, in chunks. Read this before quoting any step or figure.",
        {
            "page": ("integer", "Printed page number, 1 to {{manual_pages}}."),
            "offset": ("integer", "Characters already read. Pass nextOffset to continue while hasMore is true."),
        },
        ["page"],
    ),
    (
        "get_spec",
        "The figures this manual prints - torques, capacities, pressures, clearances, intervals - each with its page and the sentence it came from.",
        {"name": ("string", "The specification asked for, e.g. 'tyre pressure' or 'engine oil quantity'.")},
        ["name"],
    ),
    (
        "list_parts",
        "The parts this manual names, with the page they are printed on.",
        {"sectionId": ("string", "Narrow to one section id returned by find_procedure.")},
        [],
    ),
]

CLIENT_TOOL = {
    "type": "client",
    "name": "show_page",
    "description": "Put a printed page of this manual on the mechanic's screen. Call it before you read that page aloud.",
    # Nothing to wait for: the reader jumps and the agent keeps talking. `immediate` is what makes
    # the page arrive DURING the sentence that names it instead of after the turn ends.
    "expects_response": False,
    "execution_mode": "immediate",
    "parameters": {
        "type": "object",
        "properties": {"page": {"type": "integer", "description": "Printed page number to display."}},
        "required": ["page"],
    },
}


def tool_url(name: str) -> str:
    return f"{settings.public_base}/voice/elevenlabs/tools/{name}?manualId={{{{manual_id}}}}"


def webhook_headers() -> dict:
    headers = {"X-Manual-Id": "{{manual_id}}"}
    secret = os.getenv("VOICE_TOOL_SECRET")
    if secret:
        headers["X-Voice-Secret"] = secret
    return headers


def tool_configs() -> list[dict]:
    configs: list[dict] = []
    for name, description, properties, required in WEBHOOKS:
        configs.append(
            {
                "type": "webhook",
                "name": name,
                "description": description,
                # A cold on-demand page read is the slow one; 20 s is the platform default and is
                # far more than any of these has ever taken warm.
                "response_timeout_secs": 20,
                "api_schema": {
                    "url": tool_url(name),
                    "method": "POST",
                    "content_type": "application/json",
                    "request_headers": webhook_headers(),
                    "request_body_schema": {
                        "type": "object",
                        "properties": {k: {"type": t, "description": d} for k, (t, d) in properties.items()},
                        "required": required,
                    },
                },
            }
        )
    configs.append(CLIENT_TOOL)
    return configs


def agent_body(tool_ids: list[str]) -> dict:
    return {
        "name": NAME,
        "tags": [TAG],
        "conversation_config": {
            "agent": {
                # Spoken by the browser the moment the session connects, so the mechanic hears the
                # bike named back and knows the right book is open before they ask anything.
                "first_message": "I see you're looking at the {{bike_name}}.",
                "language": "en",
                "prompt": {
                    # The Deepgram grounding policy, imported rather than retyped.
                    "prompt": el.prompt_template(),
                    "llm": el.LLM,
                    "temperature": 0.0,
                    "tool_ids": tool_ids,
                },
                "dynamic_variables": {
                    "dynamic_variable_placeholders": {
                        "bike_name": "this motorcycle",
                        "manual_id": "",
                        "manual_title": "the manual",
                        "manual_pages": "0",
                        "manual_digest": "",
                    }
                },
            },
            "turn": {"turn_eagerness": "normal", "turn_timeout": 7},
            "tts": {"model_id": el.TTS_MODEL},
            "conversation": {
                "text_only": False,
                # client_tool_call is the one that matters: without it the browser never hears
                # show_page and the page never turns.
                "client_events": [
                    "conversation_initiation_metadata",
                    "audio",
                    "interruption",
                    "user_transcript",
                    "agent_response",
                    "agent_response_correction",
                    "client_tool_call",
                ],
            },
        },
        # Authorised: a bare agent id is refused, and /voice/elevenlabs/session mints the token.
        "platform_settings": {"auth": {"enable_auth": True}},
    }


def client() -> httpx.Client:
    key = settings.elevenlabs_api_key
    if not key:
        raise SystemExit(
            "no ELEVENLABS_API_KEY. Create one at elevenlabs.io and save it to "
            r"C:\Users\me\agent-secrets\elevenlabs.txt, or run with --dry-run."
        )
    return httpx.Client(base_url=API, headers={"xi-api-key": key}, timeout=60)


def existing_tools(http: httpx.Client) -> dict[str, str]:
    r = http.get("/v1/convai/tools")
    r.raise_for_status()
    out: dict[str, str] = {}
    for tool in r.json().get("tools", []):
        name = (tool.get("tool_config") or {}).get("name")
        if name:
            out[name] = tool["id"]
    return out


def sync_tools(http: httpx.Client) -> list[str]:
    known = existing_tools(http)
    ids: list[str] = []
    for config in tool_configs():
        name = config["name"]
        body = {"tool_config": config}
        if name in known:
            r = http.patch(f"/v1/convai/tools/{known[name]}", json=body)
            r.raise_for_status()
            ids.append(known[name])
        else:
            r = http.post("/v1/convai/tools", json=body)
            r.raise_for_status()
            ids.append(r.json()["id"])
        print(f"tool {name} {ids[-1]}", file=sys.stderr)
    return ids


def dry_run() -> None:
    """Every request body this script would send, and nothing sent."""
    print(f"PUBLIC_BASE {settings.public_base}")
    if not settings.public_base.startswith("https://"):
        print("  WARNING: not https - ElevenLabs cannot reach these tool endpoints", file=sys.stderr)
    for config in tool_configs():
        print(f"\nPOST /v1/convai/tools   ({config['name']})")
        print(json.dumps({"tool_config": config}, indent=2))
    print("\nPOST /v1/convai/agents/create")
    print(json.dumps(agent_body(["<tool id per tool above>"]), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", default=settings.elevenlabs_agent_id)
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the request bodies, call nothing")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return

    with client() as http:
        if args.delete:
            if args.agent_id:
                http.delete(f"/v1/convai/agents/{args.agent_id}").raise_for_status()
                print(f"deleted agent {args.agent_id}", file=sys.stderr)
            ours = {c["name"] for c in tool_configs()}
            for name, tool_id in existing_tools(http).items():
                if name in ours:
                    http.delete(f"/v1/convai/tools/{tool_id}")
                    print(f"deleted tool {name}", file=sys.stderr)
            return

        if not settings.public_base.startswith("https://"):
            print(
                f"warning: PUBLIC_BASE is {settings.public_base}; ElevenLabs cannot reach the tool endpoints",
                file=sys.stderr,
            )

        body = agent_body(sync_tools(http))
        if args.agent_id:
            http.patch(f"/v1/convai/agents/{args.agent_id}", json=body).raise_for_status()
            print(args.agent_id)
        else:
            r = http.post("/v1/convai/agents/create", json=body)
            r.raise_for_status()
            print(r.json()["agent_id"])


if __name__ == "__main__":
    main()
