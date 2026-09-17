import asyncio

from acp import run_agent

from apex_acp.agent import ApexAgent

if __name__ == "__main__":
    asyncio.run(run_agent(ApexAgent(), use_unstable_protocol=True))
