#!/usr/bin/env python3
"""
Serena MCP Server
Minimal MCP server with GitHub branch-creation support.
"""

import os, json, uuid, logging
from typing import Dict, Any
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from functools import lru_cache
import uvicorn

# ───────────────────────── Logging ──────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("serena-mcp")

# ───────────────────────── FastAPI app ───────────────────────
app = FastAPI(title="Serena MCP Server", version="1.1.0")
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
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
app.openapi = custom_openapi

# ───────────────────────── In-memory store ───────────────────
conversations: Dict[str, Any] = {}

# ───────────────────────── GitHub helper ─────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

async def gh_create_branch(repo: str, base: str, new_branch: str) -> Dict[str, Any]:
    """
    Create a branch on GitHub using the REST API.
    repo = "owner/name"   base = "main"   new_branch = "feature-x"
    """
    if not GITHUB_TOKEN:
        return {"success": False, "error": "GITHUB_TOKEN not set in Fly secrets"}

    owner, name = repo.split("/", 1)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "serena-mcp",
    }

    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        # 1) get base commit SHA
        ref_url = f"https://api.github.com/repos/{owner}/{name}/git/ref/heads/{base}"
        r = await client.get(ref_url)
        if r.status_code != 200:
            return {"success": False, "error": f"Unable to read base branch ({base}): {r.text}"}
        sha = r.json()["object"]["sha"]

        # 2) create new ref
        new_ref_url = f"https://api.github.com/repos/{owner}/{name}/git/refs"
        body = {"ref": f"refs/heads/{new_branch}", "sha": sha}
        r2 = await client.post(new_ref_url, json=body)
        if r2.status_code not in (201, 422):  # 422 = already exists
            return {"success": False, "error": f"GitHub error: {r2.text}"}

    return {"success": True, "branch": new_branch, "base_sha": sha}

# ───────────────────────── MCP router ────────────────────────
@app.post("/mcp/{function_name}")
async def handle_mcp(function_name: str, request: Request):
    try:
        params = await request.json()
    except Exception:
        params = {}

    log.info("MCP call %s  params=%s", function_name, params)

    try:
        # ───── conversation primitives ─────
        if function_name == "create_conversation":
            cid = str(uuid.uuid4())
            conversations[cid] = {
                "id": cid,
                "title": params.get("title", "New Conversation"),
                "messages": [],
            }
            return {"conversation_id": cid, "success": True}

        elif function_name == "get_conversation":
            cid = params.get("conversation_id")
            return conversations.get(cid) or {"error": "not found"}

        elif function_name == "list_conversations":
            return {"conversations": list(conversations.values())}

        elif function_name == "add_message":
            cid = params.get("conversation_id")
            if cid not in conversations:
                return {"error": "conversation not found"}
            msg = {
                "id": str(uuid.uuid4()),
                "content": params.get("content", ""),
                "role": params.get("role", "user"),
            }
            conversations[cid]["messages"].append(msg)
            return {"message_id": msg["id"], "success": True}

        elif function_name == "delete_conversation":
            cid = params.get("conversation_id")
            conversations.pop(cid, None)
            return {"success": True}

        # ───── NEW: GitHub branch creation ─────
        elif function_name == "create_branch":
            repo       = params.get("repo")      # "owner/repo"
            base       = params.get("base", "main")
            new_branch = params.get("new_branch")
            if not (repo and new_branch):
                return {"error": "repo and new_branch are required"}
            return await gh_create_branch(repo, base, new_branch)

        # ───── unknown function ─────
        else:
            return {"error": f"Function '{function_name}' not supported"}

    except Exception as e:
        log.exception("Unhandled MCP error")
        raise HTTPException(status_code=500, detail=str(e))

# ───────────────────────── health + main ─────────────────────
@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("serena_server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

