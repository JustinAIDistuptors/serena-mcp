#!/usr/bin/env python3
"""
Serena MCP Server  – drop-in replacement
Adds relay-proxy helpers so the agent can commit to GitHub
and trigger Fly.io deploys without manual copy/paste.
"""

import os
import json
import uuid
import logging
from typing import Dict, Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from functools import lru_cache
import uvicorn

# ─────────────────────────  basic logging  ──────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)s  %(name)s: %(message)s",
)
logger = logging.getLogger("serena-mcp")

# ────────────────────────  relay routing table  ─────────────────────
ROUTING_TABLE: Dict[str, str] = {
    "taskmaster": "https://taskmaster-relay.fly.dev/proxy/",
    "fileops":    "https://fileops-relay.fly.dev/proxy/",
    "serena":     "https://serena-relay.fly.dev/proxy/",
    "context7":   "https://context7-relay.fly.dev/proxy/",
    "supabase":   "https://supabase-relay.fly.dev/proxy/",
    "github":     "https://serena-relay.fly.dev/proxy/github/",  # conv. alias
    "fly":        "https://serena-relay.fly.dev/proxy/flyio/",
}

# ─────────────────────────  FastAPI setup  ──────────────────────────
app = FastAPI(title="Serena MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

@lru_cache()
def custom_openapi():
    return get_openapi(
        title=app.title,
        version="1.0.1",
        description="MCP server for Serena operations",
        routes=app.routes,
    )
app.openapi = custom_openapi

# ────────────────────────  in-memory store  ─────────────────────────
conversations: Dict[str, Dict[str, Any]] = {}

# ─────────────────────────  proxy helpers  ──────────────────────────
async def forward_to_github(path: str, payload: dict, method: str = "POST") -> dict:
    """
    Forward a JSON payload to GitHub through the relay, attaching PAT.
    """
    url = ROUTING_TABLE["github"].rstrip("/") + "/" + path.lstrip("/")
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(method, url, json=payload, headers=headers)
    logger.info(f"GitHub→{path} status={r.status_code}")
    return r.json()

async def forward_to_fly(path: str, payload: dict, method: str = "POST") -> dict:
    """
    Forward a JSON payload to Fly.io via relay, attaching auth token.
    """
    url = ROUTING_TABLE["fly"].rstrip("/") + "/" + path.lstrip("/")
    headers = {
        "Authorization": f"Bearer {os.environ['FLY_AUTH_TOKEN']}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(method, url, json=payload, headers=headers)
    logger.info(f"Fly→{path} status={r.status_code}")
    return r.json()

# ────────────────────────  MCP dispatcher  ─────────────────────────
@app.post("/mcp/{function_name}")
async def handle_mcp_request(function_name: str, request: Request):
    try:
        params = await request.json()
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}
    logger.info(f"MCP call {function_name}  params={params}")

    # ─────────────── conversation helpers (unchanged) ───────────────
    if function_name == "create_conversation":
        cid = str(uuid.uuid4())
        conversations[cid] = {
            "id": cid,
            "title": params.get("title", "New Conversation"),
            "messages": [],
            "created_at": params.get("created_at"),
            "updated_at": params.get("updated_at"),
            "metadata": params.get("metadata", {}),
        }
        return {"conversation_id": cid, "success": True}

    if function_name == "get_conversation":
        cid = params.get("conversation_id")
        if not cid or cid not in conversations:
            return {"error": "Conversation not found"}
        return {"conversation": conversations[cid]}

    if function_name == "list_conversations":
        return {"conversations": list(conversations.values())}

    if function_name == "add_message":
        cid = params.get("conversation_id")
        msg = params.get("message")
        if not cid or cid not in conversations:
            return {"error": "Conversation not found"}
        if not msg:
            return {"error": "message param required"}
        mid = str(uuid.uuid4())
        msg_obj = {
            "id": mid,
            "content": msg.get("content", ""),
            "role": msg.get("role", "user"),
            "created_at": msg.get("created_at"),
            "metadata": msg.get("metadata", {}),
        }
        conversations[cid]["messages"].append(msg_obj)
        conversations[cid]["updated_at"] = msg_obj["created_at"]
        return {"message_id": mid, "success": True}

    if function_name == "delete_conversation":
        cid = params.get("conversation_id")
        if cid in conversations:
            del conversations[cid]
            return {"success": True}
        return {"error": "Conversation not found"}

    # ──────────────── new GitHub / Fly helpers ────────────────
    if function_name == "create_branch":
        """
        params = {repo, base, new_branch}
        """
        path = "repos/{repo}/git/refs".format(repo=params["repo"])
        payload = {
            "ref": f"refs/heads/{params['new_branch']}",
            "sha": params["base"],
        }
        return await forward_to_github(path, payload)

    if function_name == "commit_files":
        """
        params = {repo, branch, files:[{path, content, message}]}
        we iterate commits so relay stays simple.
        """
        results = []
        for f in params["files"]:
            path = f"repos/{params['repo']}/contents/{f['path']}"
            payload = {
                "message": f["message"],
                "content": base64.b64encode(f["content"].encode()).decode(),
                "branch":  params["branch"],
            }
            results.append(await forward_to_github(path, payload, "PUT"))
        return {"results": results}

    if function_name == "open_pr":
        """
        params = {repo, title, head, base, body}
        """
        path = f"repos/{params['repo']}/pulls"
        payload = {
            "title": params["title"],
            "head":  params["head"],
            "base":  params["base"],
            "body":  params.get("body", ""),
        }
        return await forward_to_github(path, payload)

    if function_name == "deploy_fly":
        """
        params = {app, image_tag}
        """
        path = f"v1/apps/{params['app']}/deploys"
        payload = {"image": params["image_tag"]}
        return await forward_to_fly(path, payload)

    return {"error": f"Unknown function {function_name}"}

# ─────────────────────────────  health  ────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

# ─────────────────────────────  startup  ───────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    logger.info(f"Starting Serena MCP on :{port}")
    uvicorn.run("serena_server:app", host="0.0.0.0", port=port, reload=False)
