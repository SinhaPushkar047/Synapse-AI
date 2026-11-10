"""Tavily web search MCP server (FastMCP).

Install:  pip install fastmcp tavily-python python-dotenv
Env:      TAVILY_API_KEY=tvly-...   (or put it in a .env file)

Run (stdio, for Claude Desktop / most MCP clients):
    python tavily_mcp_server.py

Run (HTTP, for remote clients / LangGraph over URL):
    python tavily_mcp_server.py --transport http --port 8001
    -> endpoint: http://127.0.0.1:8001/mcp

Or via the FastMCP CLI:
    fastmcp run tavily_mcp_server.py --transport http --port 8001
"""

import argparse
import os
from typing import Literal, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()

API_KEY = os.getenv("TAVILY_API_KEY")
if not API_KEY:
    raise RuntimeError("TAVILY_API_KEY is not set. Add it to your environment or .env file.")

client = TavilyClient(api_key=API_KEY)
mcp = FastMCP("tavily-search")


@mcp.tool
def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    search_depth: Literal["basic", "advanced"] = "basic",
    time_range: Optional[Literal["day", "week", "month", "year"]] = None,
    include_domains: Optional[list[str]] = None,
    exclude_domains: Optional[list[str]] = None,
) -> str:
    """Search the web for current information using Tavily.

    Args:
        query: What to search for.
        max_results: Number of results to return (1-10).
        topic: "general", "news" (recent articles), or "finance".
        search_depth: "basic" is fast; "advanced" is slower but more thorough.
        time_range: Limit results to the last day/week/month/year.
        include_domains: Only return results from these domains.
        exclude_domains: Never return results from these domains.
    """
    try:
        kwargs = dict(
            query=query,
            max_results=max(1, min(max_results, 10)),
            topic=topic,
            search_depth=search_depth,
            include_answer=True,
        )
        if time_range:
            kwargs["time_range"] = time_range
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains

        resp = client.search(**kwargs)
    except Exception as e:
        return f"Search failed: {e}"

    parts = []
    if resp.get("answer"):
        parts.append(f"Summary: {resp['answer']}\n")

    for i, r in enumerate(resp.get("results", []), 1):
        parts.append(
            f"[{i}] {r.get('title', 'Untitled')}\n"
            f"URL: {r.get('url')}\n"
            f"{r.get('content', '').strip()}\n"
        )

    return "\n".join(parts) if parts else "No results found."


@mcp.tool
def extract_page(urls: list[str]) -> str:
    """Extract the full text content from one or more web page URLs.

    Args:
        urls: List of URLs to extract (use after web_search to read a page in depth).
    """
    try:
        resp = client.extract(urls=urls)
    except Exception as e:
        return f"Extraction failed: {e}"

    parts = []
    for r in resp.get("results", []):
        parts.append(f"URL: {r.get('url')}\n{r.get('raw_content', '').strip()}\n")
    for f in resp.get("failed_results", []):
        parts.append(f"Failed: {f.get('url')} ({f.get('error', 'unknown error')})")

    return "\n---\n".join(parts) if parts else "No content extracted."


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port, path="/mcp")
    else:
        mcp.run(transport="stdio")