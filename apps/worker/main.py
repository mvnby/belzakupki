from __future__ import annotations

import asyncio


async def main() -> None:
    """Worker entrypoint."""

    # TODO: Replace with real task runner (Celery/RQ/Arq).
    print("BelZakupki worker is running (placeholder)")


if __name__ == "__main__":
    asyncio.run(main())
