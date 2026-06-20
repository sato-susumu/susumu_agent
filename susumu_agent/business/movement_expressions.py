from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from susumu_agent.business.capabilities import SPEED_KEYWORDS, SPEED_MAP, SpeedLevel

ToolName = Literal["move_robot", "rotate_robot", "curve_robot", "execute_sequence", "report_unsupported"]


@dataclass(frozen=True)
class ExpressionRule:
    id: str
    text: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolPlan:
    tool: ToolName
    args: dict[str, Any]
    announcement: str
    completion: str


@dataclass(frozen=True)
class GoldenCase:
    utterance: str
    tool: ToolName
    args: dict[str, Any]
    note: str = ""


@dataclass(frozen=True)
class ContextGoldenCase:
    utterance: str
    last_command: dict[str, Any] | None
    tool: ToolName
    args: dict[str, Any]
    note: str = ""


ASR_RULES: tuple[ExpressionRule, ...] = (
    ExpressionRule("forward_asr", "「全身」→「前進」", ("全身",)),
    ExpressionRule("backward_asr", "「後退」「高体」「広大」→「後退」", ("高体", "広大")),
    ExpressionRule("low_speed_asr", "「低速」「底速」→「低速（low）」", ("底速",)),
    ExpressionRule("high_speed_asr", "「高速」「交速」→「高速（high）」", ("交速",)),
    ExpressionRule("stop_asr", "「停止」「帝止」「提示」→「停止（stop）」", ("帝止", "提示")),
    ExpressionRule(
        "rotate_asr",
        "「旋回」「千回」「先回」「1000回」「1,000回」→「旋回（rotate）」（「せんかい」の誤変換）",
        ("千回", "先回", "1000回", "1,000回"),
    ),
    ExpressionRule(
        "right_rotate_asr",
        "「右に1000回」「右に千回」→「右に旋回」（右回り）",
        ("右に1000回", "右に千回"),
    ),
    ExpressionRule(
        "left_rotate_asr",
        "「左に1000回」「左に千回」→「左に旋回」（左回り）",
        ("左に1000回", "左に千回"),
    ),
    ExpressionRule("right_face_asr", "「右に向いて」「右に向けて」→「右を向いて（rotate -90度）」", ("右に向いて", "右に向けて")),
    ExpressionRule("left_face_asr", "「左に向いて」「左に向けて」→「左を向いて（rotate +90度）」", ("左に向いて", "左に向けて")),
    ExpressionRule("front_words", "「まえ」「前」→「前進」", ("まえ", "前")),
    ExpressionRule("back_words", "「うしろ」「後ろ」「後」→「後退」", ("うしろ", "後ろ", "後")),
)

MOTION_RULES: tuple[ExpressionRule, ...] = (
    ExpressionRule(
        "linear_durationless",
        "前進・後退で時間・距離の指定なし → duration_sec=0.0（ストップ指示があるまで継続）",
        ("前進して", "後退して"),
    ),
    ExpressionRule("linear_timed", "前進・後退で時間指定あり（「3秒前進して」「三秒前進して」）→ その秒数を duration_sec に指定", ("3秒前進して", "三秒前進して")),
    ExpressionRule("linear_distance", "距離指定（「50cm」「五十センチ」「1メートル」「一メートル」）→ duration = 距離 / speed_linear 秒", ("50cm", "五十センチ", "1メートル", "一メートル")),
    ExpressionRule("one_step", "「1歩」「一歩」= 0.5m として計算", ("1歩", "一歩")),
    ExpressionRule(
        "small_amount",
        "「少し」「ちょっと」「ほんの少し」「もうちょい」+ 前進/後退 → 短時間だけ移動（安全側に倒す）",
        ("少し前進", "ちょっと後退", "ほんの少し進んで", "もうちょいバックして"),
    ),
    ExpressionRule(
        "forward_variants",
        "「進め」「前へ」「前に進んで」「まっすぐ」「直進して」→ move_robot(direction=\"forward\")",
        ("進め", "前へ", "前に進んで", "まっすぐ", "直進して"),
    ),
    ExpressionRule(
        "backward_variants",
        "「バックして」「下がって」「後ろへ」「うしろに進んで」→ move_robot(direction=\"backward\")",
        ("バックして", "下がって", "後ろへ", "うしろに進んで"),
    ),
    ExpressionRule(
        "stop_variants",
        "「止まって」「停止して」「止めて」「待って」→ move_robot(direction=\"stop\")。緊急停止語は LLM を経由せず即時停止",
        ("止まって", "停止して", "止めて", "待って"),
    ),
    ExpressionRule(
        "sequence_loop",
        "execute_sequence で時間・回数指定なし（「ジグザグに進む」「S字に進む」「蛇行して」）→ loop=true を指定してストップ指示があるまで継続",
        ("ジグザグに進む", "S字に進む", "蛇行して"),
    ),
    ExpressionRule("rotate_angle", "旋回で角度指定あり（「45度」「90度」「九十度」など）→ その角度を angle_deg に指定", ("45度", "90度", "九十度")),
    ExpressionRule(
        "rotate_continuous_left",
        "左旋回で角度指定なし・継続（「左旋回して」「くるくる回って」「左回りでくるくる」）→ continuous=True, angle_deg=1.0",
        ("左旋回して", "くるくる回って", "左回りでくるくる"),
    ),
    ExpressionRule(
        "rotate_continuous_right",
        "右旋回で角度指定なし・継続（「右回りでくるくる」「右旋回し続けて」「時計回りに回って」）→ continuous=True, angle_deg=-1.0",
        ("右回りでくるくる", "右旋回し続けて", "時計回りに回って"),
    ),
    ExpressionRule(
        "rotate_timed",
        "旋回で時間指定あり（「3秒間右に回って」「5秒間左旋回」）→ duration_sec にその秒数を指定、angle_deg は符号のみで方向指定（右=-1.0、左=1.0）",
        ("3秒間右に回って", "5秒間左旋回"),
    ),
    ExpressionRule(
        "face_direction",
        "「右を向いて」「右向け右」→ angle_deg=-90、「左を向いて」「左向け左」→ angle_deg=90",
        ("右を向いて", "右向け右", "左を向いて", "左向け左"),
    ),
    ExpressionRule(
        "turn_back",
        "「後ろを向いて」「振り向いて」「半回転して」「Uターンして」→ angle_deg=180",
        ("後ろを向いて", "振り向いて", "半回転して", "Uターンして"),
    ),
    ExpressionRule("military_turn", "「回れ右」→ angle_deg=-180、「回れ左」→ angle_deg=180", ("回れ右", "回れ左")),
    ExpressionRule(
        "corner_turn",
        "「左に曲がって」「左折して」→ angle_deg=90、「右に曲がって」「右折して」→ angle_deg=-90",
        ("左に曲がって", "左折して", "右に曲がって", "右折して"),
    ),
    ExpressionRule(
        "side_move",
        "「左に進んで」「左へ進んで」「左方向に進んで」→ execute_sequence で rotate(angle_deg=90) → move(forward) の2ステップ。右方向は angle_deg=-90",
        ("左に進んで", "左へ進んで", "左方向に進んで", "右に進んで", "右へ進んで", "右方向に進んで"),
    ),
    ExpressionRule(
        "curve_forward",
        "「左にカーブ」「左カーブしながら前進」「カーブしながら進む」→ curve_robot(direction=\"forward\", turn=\"left\")。右カーブは turn=\"right\"",
        ("左にカーブ", "左カーブしながら前進", "カーブしながら進む", "右カーブ"),
    ),
    ExpressionRule(
        "curve_backward",
        "「左にカーブしながら後退」「バックしながら右カーブ」→ curve_robot(direction=\"backward\", turn=\"left/right\")",
        ("左にカーブしながら後退", "バックしながら右カーブ"),
    ),
    ExpressionRule(
        "circle",
        "「円を描いて」「大きく回りながら進んで」→ curve_robot。左回り/反時計回りは turn=\"left\"、右回り/時計回りは turn=\"right\"",
        ("円を描いて", "大きく回りながら進んで", "左回り", "右回り"),
    ),
    ExpressionRule(
        "shape_sequences",
        "「三角形」「四角形」「正方形」→ execute_sequence で辺ごとに move → rotate を繰り返す。速度・1辺の時間指定があれば各 move に適用",
        ("三角形", "四角形", "正方形"),
    ),
    ExpressionRule(
        "last_command_reference",
        "「さっきと同じ」「もう一回」「繰り返して」→ 直前コマンドを再実行。「さっきより速く/遅く」「もっと速く/ゆっくり」→ 速度を1段階上げ下げして再実行",
        ("さっきと同じ", "もう一回", "繰り返して", "さっきより速く", "さっきより遅く", "もっと速く", "もっとゆっくり"),
    ),
    ExpressionRule("reverse_direction", "「逆方向」「反対方向」→ 直前の direction / turn / angle_deg を反転して再実行", ("逆方向", "反対方向")),
)

UNSUPPORTED_RULES: tuple[ExpressionRule, ...] = (
    ExpressionRule("conditional", "条件付き指示（「〜なければ〜して」「見つけたら〜して」）→ report_unsupported", ("なければ", "見つけたら")),
    ExpressionRule(
        "autonomy",
        "目的地移動・追跡・障害物回避など自律ナビゲーションが必要な指示 → report_unsupported",
        ("目的地まで行って", "追いかけて", "障害物を避けながら進んで"),
    ),
    ExpressionRule("destructive", "人物・動物への突進、破壊、衝突、攻撃の指示 → report_unsupported", ("突進して", "ぶつけて", "攻撃して")),
)

GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase("前進して", "move_robot", {"direction": "forward", "speed": "medium", "duration_sec": 0.0}),
    GoldenCase("ゆっくり前進して", "move_robot", {"direction": "forward", "speed": "low", "duration_sec": 0.0}),
    GoldenCase("素早く3秒前進して", "move_robot", {"direction": "forward", "speed": "high", "duration_sec": 3.0}),
    GoldenCase("三秒後退して", "move_robot", {"direction": "backward", "speed": "medium", "duration_sec": 3.0}),
    GoldenCase("一メートル進んで", "move_robot", {"direction": "forward", "speed": "medium", "duration_sec": 3.333}),
    GoldenCase("五十センチ前進して", "move_robot", {"direction": "forward", "speed": "medium", "duration_sec": 1.667}),
    GoldenCase("半メートル前進して", "move_robot", {"direction": "forward", "speed": "medium", "duration_sec": 1.667}),
    GoldenCase("バックして", "move_robot", {"direction": "backward", "speed": "medium", "duration_sec": 0.0}),
    GoldenCase("少し前進して", "move_robot", {"direction": "forward", "speed": "low", "duration_sec": 1.0}),
    GoldenCase("一歩進んで", "move_robot", {"direction": "forward", "speed": "medium", "duration_sec": 1.667}),
    GoldenCase("右を向いて", "rotate_robot", {"angle_deg": -90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("左向け左", "rotate_robot", {"angle_deg": 90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("右に90度回って", "rotate_robot", {"angle_deg": -90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("九十度右に回って", "rotate_robot", {"angle_deg": -90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("百八十度左に回って", "rotate_robot", {"angle_deg": 180.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("時計回りに回って", "rotate_robot", {"angle_deg": -1.0, "speed": "medium", "continuous": True, "duration_sec": 0.0}),
    GoldenCase("3秒間左旋回して", "rotate_robot", {"angle_deg": 1.0, "speed": "medium", "continuous": False, "duration_sec": 3.0}),
    GoldenCase("Uターンして", "rotate_robot", {"angle_deg": 180.0, "speed": "medium", "continuous": False, "duration_sec": 0.0}),
    GoldenCase("左に進んで", "execute_sequence", {"loop": False}),
    GoldenCase("右カーブしながら前進して", "curve_robot", {"direction": "forward", "turn": "right", "speed": "medium", "duration_sec": 0.0}),
    GoldenCase("円を描いて", "curve_robot", {"direction": "forward", "turn": "left", "speed": "medium", "duration_sec": 0.0}),
    GoldenCase("ジグザグに進んで", "execute_sequence", {"loop": True}),
    GoldenCase("正方形を描いて", "execute_sequence", {"loop": False}),
    GoldenCase("人にぶつけて", "report_unsupported", {"reason": "安全上対応できない指示です。"}),
)

CONTEXT_GOLDEN_CASES: tuple[ContextGoldenCase, ...] = (
    ContextGoldenCase(
        "もう一回",
        {"tool": "move_robot", "direction": "forward", "speed": "medium", "duration_sec": 2.0},
        "move_robot",
        {"direction": "forward", "speed": "medium", "duration_sec": 2.0},
    ),
    ContextGoldenCase(
        "さっきより速く",
        {"tool": "move_robot", "direction": "forward", "speed": "medium", "duration_sec": 2.0},
        "move_robot",
        {"direction": "forward", "speed": "high", "duration_sec": 2.0},
    ),
    ContextGoldenCase(
        "もっとゆっくり",
        {"tool": "move_robot", "direction": "forward", "speed": "medium", "duration_sec": 2.0},
        "move_robot",
        {"direction": "forward", "speed": "low", "duration_sec": 2.0},
    ),
    ContextGoldenCase(
        "逆方向",
        {"tool": "move_robot", "direction": "forward", "speed": "medium", "duration_sec": 2.0},
        "move_robot",
        {"direction": "backward", "speed": "medium", "duration_sec": 2.0},
    ),
    ContextGoldenCase(
        "反対方向",
        {"tool": "rotate_robot", "angle_deg": 90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0},
        "rotate_robot",
        {"angle_deg": -90.0, "speed": "medium", "continuous": False, "duration_sec": 0.0},
    ),
    ContextGoldenCase(
        "逆にして",
        {"tool": "curve_robot", "direction": "forward", "turn": "left", "speed": "medium", "duration_sec": 2.0},
        "curve_robot",
        {"direction": "backward", "turn": "right", "speed": "medium", "duration_sec": 2.0},
    ),
    ContextGoldenCase(
        "もう一回",
        {
            "tool": "execute_sequence",
            "steps": [{"type": "move", "direction": "forward", "speed": "medium", "duration_sec": 1.0}],
            "loop": False,
        },
        "execute_sequence",
        {"loop": False},
    ),
)


def format_prompt_rules(rules: tuple[ExpressionRule, ...]) -> str:
    return "\n".join(f"- {rule.text}" for rule in rules)


def format_speed_keywords() -> str:
    lines = []
    for level, words in SPEED_KEYWORDS.items():
        lines.append(f"  - {level}: {', '.join(words)}")
    return "\n".join(lines)


def normalize_text(text: str) -> tuple[str, str]:
    lowered = unicodedata.normalize("NFKC", text).strip().lower()
    compact = re.sub(r"[\s、。,.!！?？]+", "", lowered)
    return lowered, compact


_NUMBER_TOKEN = r"[0-9]+(?:\.[0-9]+)?|[零〇一二三四五六七八九十百半]+"
_KANJI_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_KANJI_UNITS = {"十": 10, "百": 100}


def parse_number_token(token: str) -> float | None:
    if token == "半":
        return 0.5
    try:
        return float(token)
    except ValueError:
        pass
    return _parse_kanji_integer(token)


def _parse_kanji_integer(token: str) -> float | None:
    total = 0
    current = 0
    for char in token:
        if char in _KANJI_DIGITS:
            current = _KANJI_DIGITS[char]
        elif char in _KANJI_UNITS:
            total += (current or 1) * _KANJI_UNITS[char]
            current = 0
        else:
            return None
    return float(total + current)


class MovementInterpreter:
    """明確な移動表現だけを LLM なしで tool plan に変換する純粋な解釈層。"""

    _SPEED_ORDER: ClassVar[tuple[SpeedLevel, ...]] = ("low", "medium", "high")
    _AMOUNT_LIMIT_WORDS: ClassVar[tuple[str, ...]] = ("ほんの少し", "少しだけ", "少し", "ちょっとだけ", "ちょっと", "もうちょい")
    _BACKWARD_WORDS: ClassVar[tuple[str, ...]] = ("後退", "バック", "下が", "後ろへ", "後ろに", "うしろへ", "うしろに", "backward", "back up", "reverse")
    _FORWARD_WORDS: ClassVar[tuple[str, ...]] = ("前進", "前へ", "前に進", "前へ進", "進め", "進んで", "進む", "まっすぐ", "真っ直ぐ", "直進", "forward", "go forward", "move forward")
    _STOP_WORDS: ClassVar[tuple[str, ...]] = ("止まって", "とまって", "停止", "止めて", "とめて", "待って", "ストップ", "stop")
    _CONTEXT_REFERENCE_WORDS: ClassVar[tuple[str, ...]] = (
        "さっき", "直前", "同じ", "もう一回", "もう1回", "繰り返", "リピート", "again", "repeat", "same",
        "逆方向", "反対方向", "逆に", "反対に", "reverse", "opposite", "もっと速", "もっとゆっくり",
    )
    _SPEED_UP_WORDS: ClassVar[tuple[str, ...]] = ("さっきより速", "もっと速", "速く", "素早く", "スピード上げ", "faster", "speed up")
    _SPEED_DOWN_WORDS: ClassVar[tuple[str, ...]] = ("さっきより遅", "もっと遅", "もっとゆっくり", "ゆっくり", "スピード落", "slower", "slow down")
    _REVERSE_WORDS: ClassVar[tuple[str, ...]] = ("逆方向", "反対方向", "逆に", "反対に", "reverse", "opposite")
    _UNSUPPORTED_SAFETY_WORDS: ClassVar[tuple[str, ...]] = ("ぶつけ", "ぶつか", "壊", "攻撃", "突進", "追突", "体当たり", "hit", "attack", "break")
    _UNSUPPORTED_AUTONOMY_WORDS: ClassVar[tuple[str, ...]] = ("追いかけ", "追跡", "ついてい", "付いてい", "障害物を避け", "目的地まで", "まで行って", "follow", "chase")

    def interpret_with_context(self, text: str, last_command: dict[str, Any] | None) -> ToolPlan | None:
        lowered, compact = normalize_text(text)
        if not compact:
            return None

        explicit_plan = self.interpret(text)
        if explicit_plan is not None:
            return explicit_plan

        context_plan = self._context_plan(lowered, compact, last_command)
        if context_plan is not None:
            return context_plan
        return None

    def interpret(self, text: str) -> ToolPlan | None:
        lowered, compact = normalize_text(text)
        if not compact:
            return None

        unsupported = self._unsupported_plan(lowered, compact)
        if unsupported is not None:
            return unsupported

        if self._contains_any(lowered, compact, self._STOP_WORDS):
            return ToolPlan(
                "move_robot",
                {"direction": "stop", "speed": "medium", "duration_sec": 0.0},
                "停止します。",
                "停止しました。",
            )

        speed = self._speed_from_text(lowered, compact)
        for builder in (
            self._shape_sequence_plan,
            self._side_move_plan,
            self._zigzag_plan,
            self._curve_plan,
            self._rotate_plan,
            self._linear_plan,
        ):
            plan = builder(lowered, compact, speed)
            if plan is not None:
                return plan
        return None

    def _context_plan(self, lowered: str, compact: str, last_command: dict[str, Any] | None) -> ToolPlan | None:
        if not self._contains_any(lowered, compact, self._CONTEXT_REFERENCE_WORDS):
            return None
        if last_command is None:
            return self._context_unsupported("直前のコマンドがないため再実行できません。")

        command = copy.deepcopy(last_command)
        if self._contains_any(lowered, compact, self._REVERSE_WORDS):
            reversed_command = self._reverse_command(command)
            if reversed_command is None:
                return self._context_unsupported("直前のコマンドは逆方向にできません。")
            return self._plan_from_command(reversed_command, "逆方向に実行します。", "逆方向の動作が完了しました。")

        if self._contains_any(lowered, compact, self._SPEED_UP_WORDS):
            adjusted = self._adjust_command_speed(command, step=1)
            if adjusted is None:
                return self._context_unsupported("直前のコマンドは速度を上げられません。")
            return self._plan_from_command(adjusted, "速度を上げて実行します。", "速度を上げた動作が完了しました。")

        if self._contains_any(lowered, compact, self._SPEED_DOWN_WORDS):
            adjusted = self._adjust_command_speed(command, step=-1)
            if adjusted is None:
                return self._context_unsupported("直前のコマンドは速度を下げられません。")
            return self._plan_from_command(adjusted, "速度を下げて実行します。", "速度を下げた動作が完了しました。")

        return self._plan_from_command(command, "直前の動作をもう一度実行します。", "直前の動作を実行しました。")

    def _context_unsupported(self, reason: str) -> ToolPlan:
        return ToolPlan("report_unsupported", {"reason": reason}, "その指示には対応できません。", reason)

    def _plan_from_command(self, command: dict[str, Any], announcement: str, completion: str) -> ToolPlan:
        tool = command.get("tool")
        args = self._tool_args(command)
        if tool not in ("move_robot", "rotate_robot", "curve_robot", "execute_sequence") or args is None:
            return self._context_unsupported("直前のコマンドを再実行できません。")
        return ToolPlan(tool, args, announcement, completion)

    def _tool_args(self, command: dict[str, Any]) -> dict[str, Any] | None:
        tool = command.get("tool")
        if tool == "move_robot":
            return {
                "direction": command.get("direction", "forward"),
                "speed": command.get("speed", "medium"),
                "duration_sec": command.get("duration_sec", 0.0),
            }
        if tool == "rotate_robot":
            return {
                "angle_deg": command.get("angle_deg", 0.0),
                "speed": command.get("speed", "medium"),
                "continuous": command.get("continuous", False),
                "duration_sec": command.get("duration_sec", 0.0),
            }
        if tool == "curve_robot":
            return {
                "direction": command.get("direction", "forward"),
                "turn": command.get("turn", "left"),
                "speed": command.get("speed", "medium"),
                "duration_sec": command.get("duration_sec", 0.0),
            }
        if tool == "execute_sequence":
            steps = command.get("steps")
            if not isinstance(steps, list):
                return None
            return {"steps": copy.deepcopy(steps), "loop": command.get("loop", False)}
        return None

    def _adjust_command_speed(self, command: dict[str, Any], step: int) -> dict[str, Any] | None:
        updated = copy.deepcopy(command)
        changed = self._adjust_speed_fields(updated, step)
        return updated if changed else None

    def _adjust_speed_fields(self, value: Any, step: int) -> bool:
        changed = False
        if isinstance(value, dict):
            if "speed" in value:
                value["speed"] = self._shift_speed(value.get("speed", "medium"), step)
                changed = True
            for child in value.values():
                changed = self._adjust_speed_fields(child, step) or changed
        elif isinstance(value, list):
            for child in value:
                changed = self._adjust_speed_fields(child, step) or changed
        return changed

    def _shift_speed(self, speed: str, step: int) -> SpeedLevel:
        if speed not in self._SPEED_ORDER:
            return "medium"
        idx = self._SPEED_ORDER.index(speed)
        next_idx = max(0, min(len(self._SPEED_ORDER) - 1, idx + step))
        return self._SPEED_ORDER[next_idx]

    def _reverse_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        tool = command.get("tool")
        updated = copy.deepcopy(command)
        if tool == "move_robot":
            direction = updated.get("direction")
            if direction == "forward":
                updated["direction"] = "backward"
                return updated
            if direction == "backward":
                updated["direction"] = "forward"
                return updated
            return None
        if tool == "rotate_robot":
            updated["angle_deg"] = -float(updated.get("angle_deg", 0.0))
            return updated
        if tool == "curve_robot":
            updated["direction"] = self._flip_direction(updated.get("direction", "forward"))
            updated["turn"] = self._flip_turn(updated.get("turn", "left"))
            return updated
        if tool == "execute_sequence":
            steps = updated.get("steps")
            if not isinstance(steps, list):
                return None
            updated["steps"] = [self._reverse_sequence_step(step) for step in reversed(steps)]
            return updated
        return None

    def _reverse_sequence_step(self, step: dict[str, Any]) -> dict[str, Any]:
        reversed_step = copy.deepcopy(step)
        step_type = reversed_step.get("type")
        if step_type == "rotate":
            reversed_step["angle_deg"] = -float(reversed_step.get("angle_deg", 0.0))
        elif step_type == "curve":
            reversed_step["direction"] = self._flip_direction(reversed_step.get("direction", "forward"))
            reversed_step["turn"] = self._flip_turn(reversed_step.get("turn", "left"))
        else:
            reversed_step["direction"] = self._flip_direction(reversed_step.get("direction", "forward"))
        return reversed_step

    def _flip_direction(self, direction: str) -> str:
        return "backward" if direction == "forward" else "forward"

    def _flip_turn(self, turn: str) -> str:
        return "right" if turn == "left" else "left"

    def _unsupported_plan(self, lowered: str, compact: str) -> ToolPlan | None:
        if "緊急停止" in compact and ("無効" in compact or "無視" in compact):
            return ToolPlan(
                "report_unsupported",
                {"reason": "緊急停止を無効化する指示には対応できません。"},
                "その指示には対応できません。",
                "緊急停止を無効化する指示には対応できません。",
            )
        if self._contains_any(lowered, compact, self._UNSUPPORTED_SAFETY_WORDS):
            return ToolPlan(
                "report_unsupported",
                {"reason": "安全上対応できない指示です。"},
                "その指示には対応できません。",
                "安全上対応できない指示です。",
            )
        if self._contains_any(lowered, compact, self._UNSUPPORTED_AUTONOMY_WORDS):
            return ToolPlan(
                "report_unsupported",
                {"reason": "自律ナビゲーションや追跡が必要な指示には対応できません。"},
                "その指示には対応できません。",
                "自律ナビゲーションや追跡が必要な指示には対応できません。",
            )
        if "なければ" in compact or "見つけたら" in compact:
            return ToolPlan(
                "report_unsupported",
                {"reason": "条件付きの自律判断が必要な指示には対応できません。"},
                "その指示には対応できません。",
                "条件付きの自律判断が必要な指示には対応できません。",
            )
        return None

    def _linear_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        direction = None
        if self._contains_any(lowered, compact, self._BACKWARD_WORDS):
            direction = "backward"
        elif self._contains_any(lowered, compact, self._FORWARD_WORDS):
            direction = "forward"
        if direction is None:
            return None

        duration_sec = self._linear_duration(lowered, compact, speed)
        label = "前進" if direction == "forward" else "後退"
        return ToolPlan(
            "move_robot",
            {"direction": direction, "speed": speed, "duration_sec": duration_sec},
            f"{label}します。",
            f"{label}しました。",
        )

    def _rotate_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        has_left = self._has_left(lowered, compact)
        has_right = self._has_right(lowered, compact)
        sign = -1.0 if has_right and not has_left else 1.0
        duration_sec = self._extract_duration_seconds(lowered, compact)
        angle = self._extract_angle_deg(compact)

        if "回れ右" in compact:
            return self._fixed_rotate(-180.0, speed)
        if "回れ左" in compact:
            return self._fixed_rotate(180.0, speed)
        if self._contains_any(lowered, compact, ("uターン", "u-turn", "後ろを向", "振り向", "半回転")):
            return self._fixed_rotate(180.0, speed)
        if self._contains_any(lowered, compact, ("右向け右", "右を向", "右向", "右に向")):
            return self._fixed_rotate(-90.0, speed)
        if self._contains_any(lowered, compact, ("左向け左", "左を向", "左向", "左に向")):
            return self._fixed_rotate(90.0, speed)
        if self._contains_any(lowered, compact, ("右折", "右に曲が", "turn right")):
            return self._fixed_rotate(-90.0, speed)
        if self._contains_any(lowered, compact, ("左折", "左に曲が", "turn left")):
            return self._fixed_rotate(90.0, speed)
        if ("1000回" in compact or "千回" in compact) and (has_left or has_right):
            return self._continuous_rotate(sign, speed)
        if angle is not None:
            if has_right:
                angle = -abs(angle)
            elif has_left:
                angle = abs(angle)
            return self._fixed_rotate(angle, speed)
        if duration_sec is not None and (has_left or has_right or self._is_rotate_like(lowered, compact)):
            return ToolPlan(
                "rotate_robot",
                {"angle_deg": sign, "speed": speed, "continuous": False, "duration_sec": duration_sec},
                "旋回します。",
                "旋回しました。",
            )
        if self._contains_any(lowered, compact, ("一回転", "1回転", "くるっと")):
            return self._fixed_rotate(sign * 360.0, speed)
        if self._is_continuous_rotation(lowered, compact) and (has_left or has_right):
            return self._continuous_rotate(sign, speed)
        return None

    def _curve_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        if not self._contains_any(lowered, compact, ("カーブ", "曲がりながら", "円を描", "回りながら進", "circle")):
            return None
        direction = "backward" if self._contains_any(lowered, compact, self._BACKWARD_WORDS) else "forward"
        turn = "right" if self._has_right(lowered, compact) else "left"
        duration_sec = self._linear_duration(lowered, compact, speed)
        return ToolPlan(
            "curve_robot",
            {"direction": direction, "turn": turn, "speed": speed, "duration_sec": duration_sec},
            "カーブ走行します。",
            "カーブ走行しました。",
        )

    def _side_move_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        side = None
        if self._contains_any(lowered, compact, ("左に進", "左へ進", "左方向に進", "左に移動", "左へ移動", "move left")):
            side = "left"
        elif self._contains_any(lowered, compact, ("右に進", "右へ進", "右方向に進", "右に移動", "右へ移動", "move right")):
            side = "right"
        if side is None:
            return None

        angle = 90.0 if side == "left" else -90.0
        duration_sec = self._linear_duration(lowered, compact, speed)
        steps = [
            {"type": "rotate", "angle_deg": angle, "speed": speed},
            {"type": "move", "direction": "forward", "speed": speed, "duration_sec": duration_sec},
        ]
        return ToolPlan(
            "execute_sequence",
            {"steps": steps, "loop": False},
            "向きを変えて進みます。",
            "移動しました。",
        )

    def _zigzag_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        if not self._contains_any(lowered, compact, ("ジグザグ", "s字", "蛇行", "左右に振", "8の字", "八の字", "zigzag")):
            return None
        explicit_duration = self._extract_duration_seconds(lowered, compact)
        step_duration = 1.0 if explicit_duration is None else max(0.1, explicit_duration / 2.0)
        steps = [
            {"type": "curve", "direction": "forward", "turn": "left", "speed": speed, "duration_sec": step_duration},
            {"type": "curve", "direction": "forward", "turn": "right", "speed": speed, "duration_sec": step_duration},
        ]
        return ToolPlan(
            "execute_sequence",
            {"steps": steps, "loop": explicit_duration is None},
            "左右に振りながら進みます。",
            "移動しました。",
        )

    def _shape_sequence_plan(self, lowered: str, compact: str, speed: SpeedLevel) -> ToolPlan | None:
        if self._contains_any(lowered, compact, ("三角形", "triangle")):
            return self._polygon_plan(sides=3, angle_deg=-120.0, speed=speed, duration_sec=self._shape_side_duration(lowered, compact, speed))
        if self._contains_any(lowered, compact, ("四角形", "正方形", "square")):
            return self._polygon_plan(sides=4, angle_deg=-90.0, speed=speed, duration_sec=self._shape_side_duration(lowered, compact, speed))
        return None

    def _polygon_plan(self, sides: int, angle_deg: float, speed: SpeedLevel, duration_sec: float) -> ToolPlan:
        steps = []
        for _ in range(sides):
            steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": duration_sec})
            steps.append({"type": "rotate", "angle_deg": angle_deg, "speed": speed})
        return ToolPlan(
            "execute_sequence",
            {"steps": steps, "loop": False},
            "図形を描くように移動します。",
            "図形移動が完了しました。",
        )

    def _fixed_rotate(self, angle_deg: float, speed: SpeedLevel) -> ToolPlan:
        return ToolPlan(
            "rotate_robot",
            {"angle_deg": angle_deg, "speed": speed, "continuous": False, "duration_sec": 0.0},
            "旋回します。",
            "旋回しました。",
        )

    def _continuous_rotate(self, sign: float, speed: SpeedLevel) -> ToolPlan:
        return ToolPlan(
            "rotate_robot",
            {"angle_deg": sign, "speed": speed, "continuous": True, "duration_sec": 0.0},
            "旋回します。",
            "旋回しました。",
        )

    def _shape_side_duration(self, lowered: str, compact: str, speed: SpeedLevel) -> float:
        duration_sec = self._linear_duration(lowered, compact, speed)
        return duration_sec if duration_sec > 0.0 else 2.0

    def _linear_duration(self, lowered: str, compact: str, speed: SpeedLevel) -> float:
        explicit = self._extract_duration_seconds(lowered, compact)
        if explicit is not None:
            return explicit
        distance = self._extract_distance_meters(lowered, compact)
        if distance is not None:
            return round(distance / SPEED_MAP[speed]["linear"], 3)
        if "一歩" in compact or "1歩" in compact:
            return round(0.5 / SPEED_MAP[speed]["linear"], 3)
        if self._contains_any(lowered, compact, self._AMOUNT_LIMIT_WORDS):
            return 1.0
        return 0.0

    def _speed_from_text(self, lowered: str, compact: str) -> SpeedLevel:
        for speed in ("high", "low", "medium"):
            if self._contains_any(lowered, compact, tuple(SPEED_KEYWORDS.get(speed, []))):
                return speed
        return "medium"

    def _has_left(self, lowered: str, compact: str) -> bool:
        return self._contains_any(lowered, compact, ("左", "反時計回り", "counterclockwise", "counter-clockwise", "left"))

    def _has_right(self, lowered: str, compact: str) -> bool:
        if self._contains_any(lowered, compact, ("反時計回り", "counterclockwise", "counter-clockwise")):
            return False
        return self._contains_any(lowered, compact, ("右", "時計回り", "clockwise", "right"))

    def _is_rotate_like(self, lowered: str, compact: str) -> bool:
        return self._contains_any(lowered, compact, ("旋回", "回転", "回って", "回り", "rotate", "turn"))

    def _is_continuous_rotation(self, lowered: str, compact: str) -> bool:
        return self._contains_any(lowered, compact, ("旋回", "回転", "回って", "回り", "くるくる", "ずっと", "し続け", "続けて", "rotate", "turn"))

    def _extract_duration_seconds(self, lowered: str, compact: str) -> float | None:
        match = re.search(rf"({_NUMBER_TOKEN})\s*(?:秒|sec(?:ond)?s?|s\b)", lowered)
        if match:
            return parse_number_token(match.group(1))
        match = re.search(rf"({_NUMBER_TOKEN})秒", compact)
        if match:
            return parse_number_token(match.group(1))
        return None

    def _extract_distance_meters(self, lowered: str, compact: str) -> float | None:
        match = re.search(rf"({_NUMBER_TOKEN})\s*(?:cm|センチ(?:メートル)?)", lowered)
        if match:
            value = parse_number_token(match.group(1))
            return None if value is None else value / 100.0
        match = re.search(rf"({_NUMBER_TOKEN})(?:cm|センチ(?:メートル)?)", compact)
        if match:
            value = parse_number_token(match.group(1))
            return None if value is None else value / 100.0
        match = re.search(rf"({_NUMBER_TOKEN})\s*(?:m|メートル)", lowered)
        if match:
            return parse_number_token(match.group(1))
        match = re.search(rf"({_NUMBER_TOKEN})(?:m|メートル)", compact)
        if match:
            return parse_number_token(match.group(1))
        return None

    def _extract_angle_deg(self, compact: str) -> float | None:
        match = re.search(rf"([+-]?(?:{_NUMBER_TOKEN}))度", compact)
        if match:
            token = match.group(1)
            sign = -1.0 if token.startswith("-") else 1.0
            value = parse_number_token(token.lstrip("+-"))
            return None if value is None else sign * value
        return None

    def _contains_any(self, lowered: str, compact: str, words: tuple[str, ...]) -> bool:
        for word in words:
            word_lowered, word_compact = normalize_text(word)
            if " " in word_lowered:
                if word_lowered in lowered:
                    return True
            elif word_compact and (word_compact in compact or word_lowered in lowered):
                return True
        return False
