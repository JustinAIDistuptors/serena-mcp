#!/usr/bin/env python3
"""
Serena MCP Server
This file implements a simple MCP server for serena operations.
"""

import base64, httpx
from routers.github_utils import upsert_file, create_pr
from routers.fly_utils import deploy_app
import os
import json
import logging
import uuid
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("serena-mcp")

# Create FastAPI app
app = FastAPI(title="Serena MCP Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for conversations
conversations = {}

# MCP endpoint
@app.post("/mcp/{function_name}")
async def handle_mcp_request(function_name: str, request: Request):
    """Handle MCP request"""
    try:
        # Parse request body
        body = await request.body()
        parameters = json.loads(body) if body else {}
        
        # Log the request
        logger.info(f"Received request for function: {function_name}")
        logger.info(f"Parameters: {parameters}")
        
        # Handle different functions
        if function_name == "create_conversation":
            conversation_id = str(uuid.uuid4())
            conversations[conversation_id] = {
                "id": conversation_id,
                "title": parameters.get("title", "New Conversation"),
                "messages": [],
                "created_at": parameters.get("created_at", "2025-04-25T00:00:00Z"),
                "updated_at": parameters.get("updated_at", "2025-04-25T00:00:00Z"),
                "metadata": parameters.get("metadata", {})
            }
            
            result = {"conversation_id": conversation_id, "success": True}
        
        elif function_name == "get_conversation":
            conversation_id = parameters.get("conversation_id")
            
            if not conversation_id:
                return {"error": "conversation_id parameter is required"}
            
            if conversation_id not in conversations:
                return {"error": f"Conversation {conversation_id} not found"}
            
            result = {"conversation": conversations[conversation_id]}
        
        elif function_name == "list_conversations":
            result = {"conversations": list(conversations.values())}
        
        elif function_name == "add_message":
            conversation_id = parameters.get("conversation_id")
            message = parameters.get("message")
            
            if not conversation_id:
                return {"error": "conversation_id parameter is required"}
            
            if not message:
                return {"error": "message parameter is required"}
            
            if conversation_id not in conversations:
                return {"error": f"Conversation {conversation_id} not found"}
            
            message_id = str(uuid.uuid4())
            message_obj = {
                "id": message_id,
                "content": message.get("content", ""),
                "role": message.get("role", "user"),
                "created_at": message.get("created_at", "2025-04-25T00:00:00Z"),
                "metadata": message.get("metadata", {})
            }
            
            conversations[conversation_id]["messages"].append(message_obj)
            conversations[conversation_id]["updated_at"] = "2025-04-25T00:00:00Z"
            
            result = {"message_id": message_id, "success": True}
        
        elif function_name == "delete_conversation":
            conversation_id = parameters.get("conversation_id")
            
            if not conversation_id:
                return {"error": "conversation_id parameter is required"}
            
            if conversation_id not in conversations:
                return {"error": f"Conversation {conversation_id} not found"}
            
            del conversations[conversation_id]
            
            result = {"success": True}
        
        else:
            return {"error": f"Function {function_name} not supported"}
        
        logger.info(f"Result: {result}")
        return result
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return {"error": "Invalid JSON in request body"}
    except Exception as e:
        logger.error(f"Error handling request: {str(e)}")
        return {"error": str(e)}

@app.get("/")
async def root():
    """Root endpoint that returns information about the server"""
    return {
        "name": "Serena MCP Server",
        "version": "1.0.0",
        "description": "MCP server for serena operations",
        "functions": ["create_conversation", "get_conversation", "list_conversations", "add_message", "delete_conversation"]
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

from functools import lru_cache
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.gzip import GZipMiddleware

# Add GZip compression for large OpenAPI responses
app.add_middleware(GZipMiddleware, minimum_size=500)

# Cached OpenAPI schema (fixes freeze on first load)
@lru_cache()
def custom_openapi():
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

app.openapi = custom_openapi

# ✅ Health check route (ready for Fly deploy + MCP health polls)
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    logger.info(f"Starting Serena MCP Server on port {port}")
    uvicorn.run("serena_server:app", host="0.0.0.0", port=port, reload=False)

