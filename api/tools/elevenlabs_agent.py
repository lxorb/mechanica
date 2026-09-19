"""Create or update the ElevenLabs agent that reads the manual out loud.

    api/.venv/Scripts/python tools/elevenlabs_agent.py            # create or update, prints the agent id
    api/.venv/Scripts/python tools/elevenlabs_agent.py --delete   # remove the agent and its tools

Needs ELEVENLABS_API_KEY (or C:\\Users\\me\\agent-secrets\\elevenlabs.txt) and PUBLIC_BASE pointing at a
reachable https URL of this API. Put the printed id in ELEVENLABS_AGENT_ID so /voice/config serves it.

UNVERIFIED: there is no ElevenLabs key on this machine, so nothing below has been run against the live
API. It is written from the 2026 Agents Platform reference. The equivalent curl, for hand checking:

    # 1. every tool is its own object; the inline conversation_config.agent.prompt.tools field is deprecated
    curl -X POST https://api.elevenlabs.io/v1/convai/tools \\
      -H "xi-api-key: $ELEVENLABS_API_KEY" -H "content-type: application/json" \\
      -d '{"tool_config":{"type":"webhook","name":"read_page","description":"...",
           "api_schema":{"url":"https://api.example.com/voice/tools/read_page","method":"POST",
             "request_body_schema":{"type":"object","properties":{
               "manualId":{"type":"string","description":"..."},
               "page":{"type":"integer","description":"..."}},"required":["manualId","page"]},
             "request_headers":{"X-Voice-Secret":"..."}}}}'
    # -> {"id":"tool_...", ...}

    # 2. the agent, referencing the tool ids
    curl -X POST https://api.elevenlabs.io/v1/convai/agents/create \\
      -H "xi-api-key: $ELEVENLABS_API_KEY" -H "content-type: application/json" \\
      -d '{"name":"Trust the manual","conversation_config":{"agent":{"first_message":"",
           "prompt":{"prompt":"...","tool_ids":["tool_..."]},
           "dynamic_variables":{"dynamic_variable_placeholders":{"bike_name":"","manual_id":""}}},
           "turn":{"turn_eagerness":"normal"}},
           "platform_settings":{"auth":{"enable_auth":false}}}'
    # -> {"agent_id":"agent_..."}

    curl -X PATCH  https://api.elevenlabs.io/v1/convai/agents/AGENT_ID -H "xi-api-key: $KEY" -d '{...}'
    curl -X DELETE https://api.elevenlabs.io/v1/convai/agents/AGENT_ID -H "xi-api-key: $KEY"
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

API = "https://api.elevenlabs.io"
NAME = "Trust the manual"

PROMPT = """You are reading the official manual for {{bike_name}} out loud to a rider standing next to the \
bike. The manual id is {{manual_id}}: pass it as manualId to every tool.

The manual's own printed words are the only thing you are allowed to say. You never answer from your own \
knowledge, you never paraphrase, you never summarise.

Every turn:
1. Call find_procedure with the rider's words. It returns the sections the manual actually prints and the \
first page.
2. Call show_page with that page so the rider sees it.
3. Call read_page for that page and read the text back exactly as printed. Say "page N" before the text of \
each page. While hasMore is true, call read_page again with nextOffset and carry on.
4. For a number - a torque, a capacity, a pressure, a clearance - call get_spec instead and read the quote \
and the page it is printed on. For a consumable or a replacement item call list_parts and read the part \
name and its spec.

Never add advice, warnings, opinions, encouragement or conclusions of your own. Never invent a page number \
or a value. If a tool returns nothing, say so in one short sentence and stop. Keep every turn short: the \
rider has dirty hands and one eye on the bike."""

WEBHOOKS = [
    (
        "find_procedure",
        "Find the sections the manual prints for what the rider wants to do. Call this first, every turn.",
        {
            "manualId": ("string", "The manual id, {{manual_id}}."),
            "query": ("string", "What the rider asked, in their own words."),
        },
        ["manualId", "query"],
    ),
    (
        "read_page",
        "Return one page of the manual verbatim, in chunks. Read it back word for word.",
        {
            "manualId": ("string", "The manual id, {{manual_id}}."),
            "page": ("integer", "1-based page number printed in the manual."),
            "offset": ("integer", "Character offset to continue from. Use nextOffset while hasMore is true."),
        },
        ["manualId", "page"],
    ),
    (
        "get_spec",
        "Return the rated values the manual prints for a name, each with its verbatim quote and page.",
        {
            "manualId": ("string", "The manual id, {{manual_id}}."),
            "name": ("string", "The printed name of the value, e.g. 'oil drain plug' or 'tyre pressure front'."),
        },
        ["manualId", "name"],
    ),
    (
        "list_parts",
        "Return the consumables and parts the manual lists for one section, with their specs.",
        {
            "manualId": ("string", "The manual id, {{manual_id}}."),
            "sectionId": ("string", "A section id returned by find_procedure."),
        },
        ["manualId", "sectionId"],
    ),
]

CLIENT_TOOL = {
    "type": "client",
    "name": "show_page",
    "description": "Show the rider a page of the manual. Call it before reading that page aloud.",
    "expects_response": False,
    "parameters": {
        "type": "object",
        "properties": {"page": {"type": "integer", "description": "1-based page number to display."}},
        "required": ["page"],
    },
}


def tool_configs() -> list[dict]:
    secret = os.getenv("VOICE_TOOL_SECRET")
    headers = {"X-Voice-Secret": secret} if secret else {}
    configs: list[dict] = []
    for name, description, properties, required in WEBHOOKS:
        configs.append(
            {
                "type": "webhook",
                "name": name,
                "description": description,
                "response_timeout_secs": 20,
                "api_schema": {
                    "url": f"{settings.public_base}/voice/tools/{name}",
                    "method": "POST",
                    "content_type": "application/json",
                    "request_body_schema": {
                        "type": "object",
                        "properties": {k: {"type": t, "description": d} for k, (t, d) in properties.items()},
                        "required": required,
                    },
                    "request_headers": headers,
                },
            }
        )
    configs.append(CLIENT_TOOL)
    return configs


def agent_body(tool_ids: list[str]) -> dict:
    return {
        "name": NAME,
        "tags": ["trustthemanual"],
        "conversation_config": {
            "agent": {
                "first_message": "",
                "language": "en",
                "prompt": {
                    "prompt": PROMPT,
                    "llm": "gpt-5.2",
                    "temperature": 0.0,
                    "tool_ids": tool_ids,
                },
                "dynamic_variables": {
                    "dynamic_variable_placeholders": {"bike_name": "this motorcycle", "manual_id": ""}
                },
            },
            "turn": {"turn_eagerness": "normal", "turn_timeout": 7},
            "tts": {"model_id": "eleven_flash_v2_5"},
            "conversation": {
                "text_only": False,
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
        "platform_settings": {"auth": {"enable_auth": False}},
    }


def client() -> httpx.Client:
    key = settings.elevenlabs_api_key
    if not key:
        raise SystemExit("no ELEVENLABS_API_KEY")
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
        print(f"tool {name} {ids[-1]}")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", default=settings.elevenlabs_agent_id)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    with client() as http:
        if args.delete:
            if args.agent_id:
                http.delete(f"/v1/convai/agents/{args.agent_id}").raise_for_status()
                print(f"deleted {args.agent_id}")
            for name, tool_id in existing_tools(http).items():
                if name in {t["name"] for t in tool_configs()}:
                    http.delete(f"/v1/convai/tools/{tool_id}")
                    print(f"deleted tool {name}")
            return

        if not settings.public_base.startswith("https://"):
            print(f"warning: PUBLIC_BASE is {settings.public_base}; ElevenLabs cannot reach it", file=sys.stderr)

        body = agent_body(sync_tools(http))
        if args.agent_id:
            r = http.patch(f"/v1/convai/agents/{args.agent_id}", json=body)
            r.raise_for_status()
            print(args.agent_id)
        else:
            r = http.post("/v1/convai/agents/create", json=body)
            r.raise_for_status()
            print(r.json()["agent_id"])


if __name__ == "__main__":
    main()
