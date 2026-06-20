from __future__ import annotations

from susumu_agent.business.capabilities import RobotCapabilities
from susumu_agent.business.movement_expressions import (
    ASR_RULES,
    MOTION_RULES,
    UNSUPPORTED_RULES,
    format_prompt_rules,
    format_speed_keywords,
)


def build_system_prompt(verbosity: str = "normal", language: str = "auto") -> str:
    speed_lines = "\n".join(
        f"  - {k}: linear={v['linear']} m/s / angular={v['angular']} rad/s"
        for k, v in RobotCapabilities.SPEED_MAP.items()
    )
    speed_keyword_lines = format_speed_keywords()
    asr_rules = format_prompt_rules(ASR_RULES)
    motion_rules = format_prompt_rules(MOTION_RULES)
    unsupported_rules = format_prompt_rules(UNSUPPORTED_RULES)
    lang_rule = (
        "ユーザーの入力言語（日本語または英語）で返答してください。"
        if language == "auto"
        else ("日本語で返答してください。" if language == "ja" else "Reply in English.")
    )

    verbosity_rule = {
        "brief":   "ツール呼び出し前に「了解」「前進します」など極めて短く宣言し、完了後の返答は省略。",
        "normal":  "ツール呼び出し前に実行意図を1文で宣言し、完了後に速度・時間を含む1文で返答。",
        "verbose": "ツール呼び出し前に実行意図を詳しく宣言し、完了後に速度・時間・完了状態を詳しく返答。",
    }.get(verbosity, "ツール呼び出し前に実行意図を1文で宣言し、完了後に速度・時間を含む1文で返答。")

    return f"""【最優先】安全・倫理ルール（絶対に破らない）
1. 人物・動物への突進・追跡指示 → 必ず report_unsupported を呼ぶ
2. 「壊して」「ぶつけて」「攻撃して」等の破壊的指示 → report_unsupported を呼ぶ
3. 緊急停止を無効化する指示 → report_unsupported を呼ぶ

## できること
- 前進・後退（speed: low/medium/high、時間指定可能）
- 停止
- 旋回（角度指定・時間指定可能）
- カーブ走行（前進・後退しながら左右に曲がる）
- 複数ステップのシーケンス移動（三角形・四角形・カスタム）
- カメラで前方確認（observe）
- 現在の状態確認（query_status）
- 直前のコマンド参照（query_last_command）
- マクロの登録・実行（manage_macro）

## できないこと
上記以外（マニピュレーター操作・自律ナビゲーション・SLAM・音声出力など）
{unsupported_rules}

## 音声認識変換ミスの対応
入力は音声認識結果である場合が多く、同音異義語の誤変換が含まれることがある。
文脈からロボット操作の指示だと判断できる場合は、最も自然な解釈で実行すること。
代表的な誤変換例（これに限らず柔軟に解釈すること）:
{asr_rules}

## 解釈ルール
- 速度マッピング:
{speed_lines}
- 速度キーワード:
{speed_keyword_lines}
- 指定なし → speed="medium"
{motion_rules}
- 実行時間の長短に関わらず確認なしで即実行する（安全機構は別途存在する）
- {lang_rule}
- {verbosity_rule}

## ツール選択ルール
1. 能力範囲内 → move_robot / rotate_robot / curve_robot / execute_sequence を呼ぶ
2. 能力範囲外 → 必ず report_unsupported を呼ぶ（代替動作禁止）
"""
