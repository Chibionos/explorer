import asyncio
from explorer.core.browser_lock import BrowserLock


async def test_lock_serializes_sections():
    lock = BrowserLock()
    log = []

    async def section(name, hold):
        async with lock.acquire():
            log.append(f"start-{name}")
            await asyncio.sleep(hold)
            log.append(f"end-{name}")

    await asyncio.gather(section("a", 0.05), section("b", 0.01))
    assert log == ["start-a", "end-a", "start-b", "end-b"]
