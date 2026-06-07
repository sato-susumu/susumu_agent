from __future__ import annotations

import os
import warnings

import yaml
from google.genai import types as genai_types

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
except ImportError:
    pass

from susumu_agent.capabilities import build_system_prompt  # noqa: E402


def _make_image_inject_callback(tools):
    """observe が保持した画像パートを LLM リクエストに追加する before_model_callback。

    InMemorySessionService の deepcopy に大きなバイナリを載せないよう、
    state 経由ではなく tools インスタンスの _pending_image_parts から直接取り出す。
    """
    def _callback(callback_context, llm_request):
        parts = tools.pop_pending_image_parts()
        if parts and llm_request.contents:
            llm_request.contents.append(
                genai_types.Content(role="user", parts=parts)
            )

    return _callback


class AgentFactory:
    def __init__(self, config: dict) -> None:
        self._config = config

    @classmethod
    def from_yaml(cls, config_path: str = "config.yaml") -> AgentFactory:
        from pathlib import Path
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        return cls(config)

    def _configure_env(self, llm_cfg: dict) -> None:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or llm_cfg.get("project", "")
        if project:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project
        os.environ["GOOGLE_CLOUD_LOCATION"] = llm_cfg.get("location", "asia-northeast1")
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

    def _validate_model(self, model: str) -> None:
        if "claude" in model.lower() and not _CLAUDE_REGISTERED:
            raise RuntimeError(
                f"モデル '{model}' は Claude ですが、Vertex AI での Claude アクセスが\n"
                "有効化されていません。\n"
                "config.yaml の llm.model を 'gemini-2.5-flash' 等の Gemini モデルに変更してください。"
            )

    def create_agent(self, tools_list: list, tools_instance=None) -> "LlmAgent":
        if not ADK_AVAILABLE:
            raise RuntimeError(
                "google-adk がインストールされていません。\n"
                "pip install google-adk anthropic[vertex] を実行してください。"
            )

        llm_cfg = self._config.get("llm", {})
        iface_cfg = self._config.get("interface", {})
        model = llm_cfg.get("model", "gemini-2.5-flash")

        self._configure_env(llm_cfg)
        self._validate_model(model)

        system_prompt = build_system_prompt(
            verbosity=iface_cfg.get("verbosity", "normal"),
            language=iface_cfg.get("language", "auto"),
        )

        kwargs = dict(
            name="robot_controller",
            model=model,
            instruction=system_prompt,
            tools=tools_list,
        )
        if tools_instance is not None:
            kwargs["before_model_callback"] = _make_image_inject_callback(tools_instance)

        return LlmAgent(**kwargs)
