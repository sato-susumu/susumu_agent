from __future__ import annotations

import os
import warnings

import yaml

# ADK の実験的機能に関する UserWarning を抑制
warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

ADK_AVAILABLE = False
try:
    from google.adk.agents import LlmAgent
    ADK_AVAILABLE = True
except ImportError:
    pass

_CLAUDE_REGISTERED = False
try:
    from google.adk.models.anthropic_llm import Claude
    from google.adk.models.registry import LLMRegistry
    LLMRegistry.register(Claude)
    _CLAUDE_REGISTERED = True
except Exception:
    pass

from susumu_agent.capabilities import build_system_prompt  # noqa: E402


class AgentFactory:
    def __init__(self, config: dict) -> None:
        self._config = config

    @classmethod
    def from_yaml(cls, config_path: str = "config.yaml") -> "AgentFactory":
        from pathlib import Path
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        return cls(config)

    def create_agent(self, tools: list) -> "LlmAgent":
        if not ADK_AVAILABLE:
            raise RuntimeError(
                "google-adk がインストールされていません。\n"
                "pip install google-adk anthropic[vertex] を実行してください。"
            )

        llm_cfg = self._config.get("llm", {})
        iface_cfg = self._config.get("interface", {})

        model = llm_cfg.get("model", "gemini-2.5-flash")
        if not llm_cfg.get("model_locked", False):
            model = os.environ.get("ROBOT_MODEL", model)

        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or llm_cfg.get("project", "")
        if project:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project
        location = os.environ.get("GOOGLE_CLOUD_LOCATION") or llm_cfg.get("location", "asia-northeast1")
        os.environ["GOOGLE_CLOUD_LOCATION"] = location
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

        is_claude = "claude" in model.lower()
        if is_claude and not _CLAUDE_REGISTERED:
            raise RuntimeError(
                f"モデル '{model}' は Claude ですが、Vertex AI での Claude アクセスが\n"
                "有効化されていません。\n"
                "config.yaml の llm.model を 'gemini-2.5-flash' 等の Gemini モデルに変更してください。"
            )

        system_prompt = build_system_prompt(
            verbosity=iface_cfg.get("verbosity", "normal"),
            language=iface_cfg.get("language", "auto"),
        )

        return LlmAgent(
            name="robot_controller",
            model=model,
            instruction=system_prompt,
            tools=tools,
        )
