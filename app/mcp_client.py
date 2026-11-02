
import asyncio
import logging
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_PATH = PROJECT_ROOT / "mcp_server.py"


async def save_reservation(
    request_id: str,
    name: str,
    car_number: str,
    reservation_period: str,
    approval_time: str,
) -> str:
    """Call the MCP server to save an approved reservation."""

    server_params = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "python",
            str(MCP_SERVER_PATH),
        ],
        env=None,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "save_confirmed_reservation",
                    arguments={
                        "request_id": request_id,
                        "name": name,
                        "car_number": car_number,
                        "reservation_period": reservation_period,
                        "approval_time": approval_time,
                    },
                )

                if result.isError:
                    raise RuntimeError(
                        "MCP server rejected the reservation write."
                    )

                return "\n".join(
                    item.text
                    for item in result.content
                    if hasattr(item, "text")
                )

    except Exception:
        logger.exception("MCP reservation storage call failed")
        raise RuntimeError(
            "Unable to save the approved reservation through MCP."
        )


def save_reservation_sync(
    request_id: str,
    name: str,
    car_number: str,
    reservation_period: str,
    approval_time: str,
) -> str:
    """
    Synchronous wrapper for the existing synchronous LangGraph nodes.

    This is intended for the CLI workflow, where no asyncio event loop
    is already running in the calling thread.
    """

    return asyncio.run(
        save_reservation(
            request_id=request_id,
            name=name,
            car_number=car_number,
            reservation_period=reservation_period,
            approval_time=approval_time,
        )
    )
