"""Minimal MCP client: Hark (an AI agent) talks to the Tiger MCP server over stdio."""
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TIGER = os.path.expanduser("~/bin/tiger")

async def main():
    params = StdioServerParameters(command=TIGER, args=["--password-storage", "pgpass", "mcp", "start"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print(f"Connected to MCP server: {init.server_info.name} {init.server_info.version}")
            tools = await s.list_tools()
            print(f"\n{len(tools.tools)} tools exposed:")
            for t in tools.tools:
                print(f"  - {t.name}")
            for name, args in json.loads(sys.argv[1]) if len(sys.argv) > 1 else []:
                print(f"\n>>> call {name} {json.dumps(args)}")
                res = await s.call_tool(name, args)
                for c in res.content:
                    print(getattr(c, "text", c)[:3000])

asyncio.run(main())
