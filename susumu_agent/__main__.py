"""python -m susumu_agent で起動するエントリポイント。"""
import asyncio

from susumu_agent.main import main

if __name__ == "__main__":
    asyncio.run(main())
