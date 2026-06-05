from __future__ import annotations
from abc import ABC, abstractmethod


class BaseRecognizer(ABC):
    """音声認識の抽象基底クラス。自前実装はこれを継承する。"""

    @abstractmethod
    async def recognize(self) -> str:
        """マイク入力を受け取りテキストを返す。"""
        ...


class StdinRecognizer(BaseRecognizer):
    """テスト用：標準入力をそのまま返すフォールバック実装。"""

    async def recognize(self) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, input)
