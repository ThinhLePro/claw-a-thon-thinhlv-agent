"""MCP Client — Auto-discover and register tools from MCP Server.

Connects to the MCP server at startup, discovers all available tools,
and creates LangChain-compatible tool wrappers automatically.
This eliminates the need to manually maintain 15+ wrapper functions.
"""

import asyncio
import concurrent.futures
import logging
import time
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)


def call_mcp_tool(mcp_server_url: str, name: str, arguments: dict, max_retries: int = 3) -> str:
    """Call an MCP tool synchronously via the SSE transport.

    Uses a dedicated thread with a fresh event loop to avoid conflicts
    with any already-running event loop (e.g. Telegram bot polling).
    Automatically retries transient connection errors with exponential backoff.
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async def _call():
        async with sse_client(mcp_server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                res = await session.call_tool(name, arguments=arguments)
                # Combine text content
                return "".join(c.text for c in res.content if hasattr(c, "text"))

    def _run_in_new_loop():
        """Run the async MCP call in a brand-new event loop on this thread."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_in_new_loop)
                return future.result(timeout=30)
        except Exception as e:
            last_error = e
            # Extract clean error message
            error_msg = str(e)
            if hasattr(e, "exceptions"):
                sub_errs = [f"{type(sub).__name__}: {sub}" for sub in e.exceptions]
                error_msg = "; ".join(sub_errs)

            # Check if this is a transient connection error worth retrying
            is_transient = any(kw in error_msg.lower() for kw in
                ["connect", "timeout", "refused", "unreachable", "reset", "taskgroup"])

            if is_transient and attempt < max_retries:
                wait_time = 2 ** attempt  # 2s, 4s
                logger.warning(
                    f"MCP tool '{name}' attempt {attempt}/{max_retries} failed: {error_msg}. "
                    f"Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                continue

            # Final attempt or non-transient error — log and return error
            logger.error(f"MCP tool '{name}' failed after {attempt} attempt(s): {error_msg}")
            break

    return (
        f"Error: Tool '{name}' failed after {max_retries} attempts. "
        f"Last error: {last_error}. "
        f"The MCP Gateway Server may be unreachable. Please check connectivity."
    )


def _mcp_type_to_python(json_type: str) -> type:
    """Convert JSON Schema type to Python type."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }
    return mapping.get(json_type, str)


def discover_mcp_tools(mcp_server_url: str, max_retries: int = 5) -> list:
    """Connect to MCP server, list tools, auto-create LangChain tool wrappers.

    Args:
        mcp_server_url: SSE endpoint URL of the MCP server.
        max_retries: Number of retry attempts to connect to the MCP server.

    Returns:
        List of LangChain StructuredTool instances, one per MCP tool.
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async def _discover():
        async with sse_client(mcp_server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return tools_result.tools

    def _run_in_new_loop():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_discover())
        finally:
            loop.close()

    # Retry connection to MCP server with exponential backoff
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_in_new_loop)
                mcp_tools = future.result(timeout=30)
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

    langchain_tools = []
    for mcp_tool in mcp_tools:
        tool_name = mcp_tool.name
        tool_description = mcp_tool.description or f"MCP tool: {tool_name}"
        input_schema = mcp_tool.inputSchema or {}

        # Build Pydantic model for the tool's input schema
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

        # Create dynamic Pydantic model
        if field_definitions:
            ArgsModel = create_model(f"{tool_name}_args", **field_definitions)
        else:
            ArgsModel = create_model(f"{tool_name}_args")

        # Create closure that captures tool_name and mcp_server_url
        def _make_tool_fn(captured_name: str, captured_url: str):
            def tool_fn(**kwargs) -> str:
                return call_mcp_tool(captured_url, captured_name, kwargs)
            return tool_fn

        lc_tool = StructuredTool(
            name=tool_name,
            description=tool_description,
            func=_make_tool_fn(tool_name, mcp_server_url),
            args_schema=ArgsModel,
        )
        langchain_tools.append(lc_tool)

    logger.info(
        f"Discovered {len(langchain_tools)} MCP tools from {mcp_server_url}: "
        f"{[t.name for t in langchain_tools]}"
    )
    return langchain_tools
