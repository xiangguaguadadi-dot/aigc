"""Quick test for Tripo API proxy connection"""
import asyncio
import sys
sys.path.insert(0, ".")

from tripo_client import TripoConverter

async def test():
    async with TripoConverter() as converter:
        balance = await converter.client.get_balance()
        print(f"Balance: {balance}")

asyncio.run(test())
