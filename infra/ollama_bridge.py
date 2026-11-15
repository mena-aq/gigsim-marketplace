"""Bridge Docker's host gateway to the existing loopback-only Ollama service.

Runs with host networking on Linux. No requests or responses are logged or stored.
"""

import asyncio
import os
from contextlib import suppress


async def copy_stream(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream = None
    try:
        remote_reader, upstream = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 11434), timeout=5
        )
        await asyncio.gather(
            copy_stream(reader, upstream), copy_stream(remote_reader, writer)
        )
    except (OSError, TimeoutError):
        pass  # Availability is reported by the container health check.
    finally:
        for stream in (upstream, writer):
            if stream is not None:
                stream.close()
                with suppress(OSError):
                    await stream.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(
        forward,
        host=os.getenv("OLLAMA_BRIDGE_HOST", "host.docker.internal"),
        port=11435,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
