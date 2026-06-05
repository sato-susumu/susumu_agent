from __future__ import annotations
from abc import ABC, abstractmethod


class BaseSynthesizer(ABC):
    """音声合成の抽象基底クラス。自前実装はこれを継承する。"""

    @abstractmethod
    async def speak(self, text: str) -> None:
        """テキストを音声で出力する。"""
        ...


class PrintSynthesizer(BaseSynthesizer):
    """フォールバック実装：音声なしでテキストのみ出力する。"""

    async def speak(self, text: str) -> None:
        print(f"[TTS] {text}")
