"""MCP Client — Auto-discover and register tools from MCP Server.
"""

import asyncio
import logging
import time
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)


def call_mcp_tool(mcp_server_url: str, name: str, arguments: dict, max_retries: int = 3) -> str:
    """Call an MCP tool synchronously via the SSE transport.
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async def _call():
        async with sse_client(mcp_server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                res = await session.call_tool(name, arguments=arguments)
                raw_text = "".join(c.text for c in res.content if hasattr(c, "text"))
                MAX_CHARS = 30000
                if len(raw_text) > MAX_CHARS:
                    logger.warning(f"MCP tool '{name}' output truncated from {len(raw_text)} to {MAX_CHARS} chars.")
                    return (
                        raw_text[:MAX_CHARS] + 
                        f"\n\n... [OUTPUT TRUNCATED - Showing first {MAX_CHARS} characters of {len(raw_text)} total characters to prevent context window overflow] ..."
                    )
                return raw_text

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(asyncio.wait_for(_call(), timeout=30))
            finally:
                loop.close()
        except Exception as e:
            last_error = e
            error_msg = str(e)
            if hasattr(e, "exceptions"):
                sub_errs = [f"{type(sub).__name__}: {sub}" for sub in e.exceptions]
                error_msg = "; ".join(sub_errs)

            is_transient = any(kw in error_msg.lower() for kw in
                ["connect", "timeout", "refused", "unreachable", "reset", "taskgroup"])

            if is_transient and attempt < max_retries:
                wait_time = 2 ** attempt
                logger.warning(
                    f"MCP tool '{name}' attempt {attempt}/{max_retries} failed: {error_msg}. "
                    f"Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                continue
            logger.error(f"MCP tool '{name}' failed after {attempt} attempt(s): {error_msg}")
            break

    return (
        f"Error: Tool '{name}' failed after {max_retries} attempts. "
        f"Last error: {last_error}. "
        f"The MCP Gateway Server may be unreachable. Please check connectivity."
    )


def _mcp_type_to_python(json_type: str) -> type:
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }
    return mapping.get(json_type, str)


def discover_mcp_tools(mcp_server_url: str, agent_name: str = None, redis_client: Any = None, max_retries: int = 5) -> list:
    """Connect to MCP server, list tools, auto-create LangChain tool wrappers, and filter by Redis ACL.
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async def _discover():
        async with sse_client(mcp_server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return tools_result.tools

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            loop = asyncio.new_event_loop()
            try:
                mcp_tools = loop.run_until_complete(asyncio.wait_for(_discover(), timeout=30))
            finally:
                loop.close()
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.warning(
                    f"MCP discovery attempt {attempt}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"Failed to discover MCP tools after {max_retries} attempts: {last_error}"
                )
                raise RuntimeError(
                    f"Cannot connect to MCP server at {mcp_server_url}. "
                    f"Last error: {last_error}"
                ) from last_error

    allowed_tools = set()
    if agent_name and redis_client:
        try:
            key = f"acl:tools:{agent_name}"
            members = redis_client.smembers(key)
            if members:
                allowed_tools = set(members)
                logger.info(f"Loaded {len(allowed_tools)} allowed tools from Redis ACL for {agent_name}: {allowed_tools}")
            else:
                logger.warning(f"No allowed tools found in Redis for {agent_name}. Will allow all tools.")
        except Exception as e:
            logger.error(f"Failed to fetch tool ACL from Redis for {agent_name}: {e}")

    langchain_tools = []
    for mcp_tool in mcp_tools:
        tool_name = mcp_tool.name
        
        # Apply Redis ACL filter if configured
        if allowed_tools and tool_name not in allowed_tools:
            logger.debug(f"Skipping tool '{tool_name}' - not in ACL for {agent_name}")
            continue

        tool_description = mcp_tool.description or f"MCP tool: {tool_name}"
        input_schema = mcp_tool.inputSchema or {}

        properties = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))

        field_definitions = {}
        for param_name, param_info in properties.items():
            param_type = _mcp_type_to_python(param_info.get("type", "string"))
            param_desc = param_info.get("description", "")
            default_val = param_info.get("default")

            if param_name in required_fields:
                field_definitions[param_name] = (
                    param_type,
                    Field(description=param_desc),
                )
            else:
                field_definitions[param_name] = (
                    param_type,
                    Field(default=default_val, description=param_desc),
                )

        if field_definitions:
            ArgsModel = create_model(f"{tool_name}_args", **field_definitions)
        else:
            ArgsModel = create_model(f"{tool_name}_args")

        def _make_tool_fn(captured_name: str, captured_url: str):
            def tool_fn(**kwargs) -> str:
                if captured_name == "send_notification":
                    if not kwargs.get("session_id"):
                        try:
                            from context import thread_local
                            if hasattr(thread_local, "session_id") and thread_local.session_id:
                                kwargs["session_id"] = thread_local.session_id
                        except Exception as ex:
                            logger.warning(f"Failed to auto-inject session_id from thread_local: {ex}")
                return call_mcp_tool(captured_url, captured_name, kwargs)
            return tool_fn

        lc_tool = StructuredTool(
            name=tool_name,
            description=tool_description,
            func=_make_tool_fn(tool_name, mcp_server_url),
            args_schema=ArgsModel,
        )
        langchain_tools.append(lc_tool)

    return langchain_tools
