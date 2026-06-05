from __future__ import annotations
import os
import warnings
import yaml
from pathlib import Path

# ADK の実験的機能に関する UserWarning を抑制
warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

# ─── ADK のインポート（インストールされていない場合は起動時にエラー） ───
ADK_AVAILABLE = False
try:
    from google.adk.agents import LlmAgent
    ADK_AVAILABLE = True
except ImportError:
    pass

# Claude (Vertex AI) が使える場合のみ登録
_CLAUDE_REGISTERED = False
try:
    from google.adk.models.anthropic_llm import Claude
    from google.adk.models.registry import LLMRegistry
    LLMRegistry.register(Claude)
    _CLAUDE_REGISTERED = True
except Exception:
    pass

from capabilities import build_system_prompt
from tools import ALL_TOOLS


def load_config(config_path: str = "config.yaml") -> dict:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def create_agent(config: dict) -> "LlmAgent":
    if not ADK_AVAILABLE:
        raise RuntimeError(
            "google-adk がインストールされていません。\n"
            "pip install google-adk anthropic[vertex] を実行してください。"
        )

    llm_cfg = config.get("llm", {})
    iface_cfg = config.get("interface", {})

    model = llm_cfg.get("model", "gemini-2.5-flash")
    if not llm_cfg.get("model_locked", False):
        model = os.environ.get("ROBOT_MODEL", model)

    # Vertex AI 環境変数を設定
    project = llm_cfg.get("project", "")
    if project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = llm_cfg.get("location", "us-central1")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

    # Claude モデルを指定しているが登録できていない場合は警告
    is_claude = "claude" in model.lower()
    if is_claude and not _CLAUDE_REGISTERED:
        raise RuntimeError(
            f"モデル '{model}' は Claude ですが、Vertex AI での Claude アクセスが\n"
            "有効化されていません。\n"
            "GCP コンソール → Vertex AI → Model Garden → Claude で利用申請するか、\n"
            "config.yaml の llm.model を 'gemini-2.5-flash' 等の Gemini モデルに変更してください。"
        )

    system_prompt = build_system_prompt(
        verbosity=iface_cfg.get("verbosity", "normal"),
        language=iface_cfg.get("language", "auto"),
    )

    agent = LlmAgent(
        name="robot_controller",
        model=model,
        instruction=system_prompt,
        tools=ALL_TOOLS,
    )
    return agent
