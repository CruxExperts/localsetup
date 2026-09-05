"""Isolated named-command tool delegates execution to supervisor recipes."""
from __future__ import annotations
import sys
from .sdk_tool_checkpoint import pretool_checkpoint


def process_tool(finder,channel):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK process tools require the active isolated worker importer')
    finder.verify_origins()
    from pydantic_ai.tools import Tool
    async def run_command(ctx,name:str)->dict:
        """Run a supervisor-granted named command on its approved input snapshot."""
        checkpoint=await pretool_checkpoint(finder,channel,ctx)
        return await channel.request_async('process.run',{'name':name,'checkpoint':checkpoint,'call_id':ctx.tool_call_id})
    tool=Tool(run_command,takes_ctx=True,sequential=True,max_retries=0)
    finder.verify_origins()
    return tool
