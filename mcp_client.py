"""Small MCP stdio client used by the agent to discover and invoke real server tools."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import sys
from typing import Any
from config import ROOT_DIR, get_settings


def _open_session():
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT_DIR / "mcp_server.py")],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return stdio_client(params)


async def _list_tools_async() -> list[dict]:
    from mcp import ClientSession
    async with _open_session() as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return [{"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema}
                    for tool in response.tools]


async def _call_tool_async(name: str, arguments: dict) -> Any:
    from mcp import ClientSession
    async with _open_session() as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tool_list = await session.list_tools()
            allowed = {tool.name for tool in tool_list.tools}
            if name not in allowed:
                raise ValueError(f"MCP tool '{name}' is not exposed by the server.")
            result = await session.call_tool(name, arguments=arguments)
            if result.isError:
                parts = [getattr(part, "text", "") for part in (result.content or [])]
                raise RuntimeError("MCP tool error: " + "\n".join(p for p in parts if p))
            structured = getattr(result, "structuredContent", None)
            if structured is not None:
                return structured
            texts = [getattr(part, "text", "") for part in (result.content or []) if getattr(part, "text", None)]
            if not texts:
                return {}
            text = "\n".join(texts)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}


def list_tools() -> list[dict]:
    timeout = get_settings().step_timeout_seconds
    return asyncio.run(asyncio.wait_for(_list_tools_async(), timeout=timeout))


def call_tool(name: str, arguments: dict, timeout_seconds: float | None = None) -> Any:
    # A caller may supply the remaining task budget; the step timeout is always an upper bound.
    step_timeout = get_settings().step_timeout_seconds
    timeout = min(step_timeout, timeout_seconds) if timeout_seconds is not None else step_timeout
    if timeout <= 0:
        raise TimeoutError(f"No time budget remains for MCP tool '{name}'.")
    return asyncio.run(asyncio.wait_for(_call_tool_async(name, arguments), timeout=timeout))
