import asyncio
from wq_bus.ai.adapters.copilot_cli import CopilotAdapter

async def main():
    a = CopilotAdapter()
    msgs = [{"role": "user", "content": "Reply with only this JSON: {\"msg\":\"hi\"}"}]
    out = await a.call(msgs, "claude-sonnet-4.6")
    print("OUT:", repr(out[:300]))

if __name__ == "__main__":
    asyncio.run(main())
