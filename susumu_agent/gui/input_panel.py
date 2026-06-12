"""/from_human トピックに文字列を送る GUI パネル。

左ペイン: 入力（選択式 / 自由入力をラジオボタンで切り替え）
右ペイン: /from_human・/to_human・/agent_event の最新メッセージを表示
"""
from __future__ import annotations

import contextlib
import json
import random
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import rclpy
from loguru import logger
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

# 語順: 列1（量・程度）+ 列2（速さ・様子）+ 列3（動作）→ 例「少しゆっくり前進して」
_WORD_POOLS: list[list[str]] = [
    # 列1: 量・程度（省略可）
    [
        "",
        "少し", "ちょっと", "もう少し", "たくさん",
        "大きく", "小さく", "ほんの少し", "思いっきり",
        "かなり", "ぐるっと", "半回転", "一回転",
        "90度", "180度", "360度",
    ],
    # 列2: 速さ・様子（省略可）
    [
        "",
        "ゆっくり", "普通の速さで", "速く", "素早く",
        "のんびり", "慎重に", "思い切り", "静かに",
        "スムーズに", "一気に", "じわじわ",
    ],
    # 列3: 動作（必須）
    [
        "前進して", "後退して",
        "左に曲がって", "右に曲がって",
        "左旋回して", "右旋回して",
        "左に進んで", "右に進んで",
        "Uターンして",
        "その場で左回転して", "その場で右回転して",
        "止まって",
    ],
]

_DISPLAY_COUNT = 5

_FONT_BASE    = ("Noto Sans CJK JP", 14)
_FONT_LABEL   = ("Noto Sans CJK JP", 13)
_FONT_PREVIEW = ("Noto Sans CJK JP", 15, "bold")
_FONT_MONO    = ("Monospace", 12)
_BTN_PAD      = (24, 12)   # Big.TButton の padding (x, y)

# 右ペインの各トピックに表示する最大行数
_MAX_LOG_LINES = 30


def _sample_column(pool: list[str]) -> list[str]:
    candidates = [w for w in pool if w != ""]
    n = min(_DISPLAY_COUNT, len(candidates))
    sampled = random.sample(candidates, n)
    if "" in pool:
        sampled.append("")
    return sampled


class InputPanelApp:
    def __init__(
        self,
        node: Node,
        from_human_topic: str = "/from_human",
        to_human_topic: str = "/to_human",
        agent_event_topic: str = "/agent_event",
        stt_event_topic: str = "/stt_event",
    ) -> None:
        self._node = node
        self._pub = node.create_publisher(String, from_human_topic, 10)

        # サブスクライバ（スレッドセーフに after() で GUI 更新）
        node.create_subscription(String, from_human_topic,
                                 lambda m: self._on_topic("from_human", m.data), 10)
        node.create_subscription(String, to_human_topic,
                                 lambda m: self._on_topic("to_human", m.data), 10)
        node.create_subscription(String, agent_event_topic,
                                 lambda m: self._on_topic("agent_event", m.data), 10)
        node.create_subscription(String, stt_event_topic,
                                 lambda m: self._on_topic("stt_event", m.data), 10)

        self._root = tk.Tk()
        self._root.title("/from_human 送信パネル")
        self._root.resizable(True, True)

        style = ttk.Style(self._root)
        style.configure(".", font=_FONT_BASE)
        style.configure("TLabelframe.Label", font=_FONT_BASE)
        style.configure("Big.TButton", font=_FONT_BASE, padding=_BTN_PAD)

        self._input_mode = tk.StringVar(value="word")
        self._selected: list[tk.StringVar] = []
        self._col_frames: list[ttk.LabelFrame] = []
        self._current_words: list[list[str]] = []
        self._preview_var = tk.StringVar()
        self._free_text: tk.Text

        # 右ペイン用テキストウィジェット
        self._log_texts: dict[str, tk.Text] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 6}

        # 左右を並べる PanedWindow
        paned = ttk.PanedWindow(self._root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        self._build_left(left, pad)
        self._build_right(right, pad)

    # ---------- 左ペイン ----------
    def _build_left(self, parent: ttk.Frame, pad: dict) -> None:
        mode_frame = ttk.LabelFrame(parent, text="入力方法")
        mode_frame.pack(fill="x", pady=(0, 6))
        ttk.Radiobutton(mode_frame, text="選択式入力", variable=self._input_mode,
                        value="word", command=self._on_mode_change,
                        ).pack(side="left", padx=12, pady=6)
        ttk.Radiobutton(mode_frame, text="自由入力", variable=self._input_mode,
                        value="free", command=self._on_mode_change,
                        ).pack(side="left", padx=12, pady=6)

        self._word_frame = ttk.Frame(parent)
        self._free_frame = ttk.Frame(parent)
        self._build_word_selector(self._word_frame, pad)
        self._build_free_input(self._free_frame, pad)
        self._show_mode("word")

    def _on_mode_change(self) -> None:
        self._show_mode(self._input_mode.get())

    def _show_mode(self, mode: str) -> None:
        if mode == "word":
            self._free_frame.pack_forget()
            self._word_frame.pack(fill="both", expand=True)
        else:
            self._word_frame.pack_forget()
            self._free_frame.pack(fill="both", expand=True)

    def _build_word_selector(self, parent: ttk.Frame, pad: dict) -> None:
        col_container = ttk.Frame(parent)
        col_container.pack(fill="both", expand=True)
        self._col_container = col_container

        self._selected = []
        self._col_frames = []
        self._current_words = []

        for col_idx in range(len(_WORD_POOLS)):
            words = _sample_column(_WORD_POOLS[col_idx])
            self._current_words.append(words)

            var = tk.StringVar(value=words[0] if words else "")
            self._selected.append(var)

            col_box = ttk.LabelFrame(col_container, text=f"列 {col_idx + 1}")
            col_box.grid(row=0, column=col_idx, sticky="nsew", padx=4, pady=4)
            col_container.columnconfigure(col_idx, weight=1)
            self._col_frames.append(col_box)
            self._populate_column(col_box, words, var, pad)

            # 各列の真下にプレビューラベル
            pv = tk.StringVar(value=words[0] or "（なし）")
            ttk.Label(col_container, textvariable=pv, foreground="blue",
                      font=_FONT_PREVIEW, anchor="center",
                      ).grid(row=1, column=col_idx, sticky="ew", padx=4, pady=(0, 4))
            var.trace_add("write", lambda *_, v=var, p=pv: p.set(v.get() or "（なし）"))

        for var in self._selected:
            var.trace_add("write", self._update_preview)
        self._update_preview()

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", **pad)
        ttk.Button(btn_frame, text="クリア", style="Big.TButton",
                   command=self._clear_selection).pack(side="left")
        ttk.Button(btn_frame, text="リロード", style="Big.TButton",
                   command=self._reshuffle_columns).pack(side="left", padx=(8, 0))
        ttk.Button(btn_frame, text="ストップ", style="Big.TButton",
                   command=self._send_stop).pack(side="left", padx=(8, 0))
        ttk.Button(btn_frame, text="送信 →", style="Big.TButton",
                   command=self._send_word_selection).pack(side="right")

    def _populate_column(self, col_box: ttk.LabelFrame, words: list[str],
                         var: tk.StringVar, pad: dict) -> None:
        for child in col_box.winfo_children():
            child.destroy()
        for word in words:
            ttk.Radiobutton(col_box, text=word or "（なし）",
                            variable=var, value=word).pack(anchor="w", **pad)

    def _reshuffle_columns(self) -> None:
        pad = {"padx": 8, "pady": 6}
        for i in range(len(_WORD_POOLS)):
            words = _sample_column(_WORD_POOLS[i])
            self._current_words[i] = words
            self._selected[i].set(words[0] if words else "")
            self._populate_column(self._col_frames[i], words, self._selected[i], pad)
        self._update_preview()

    def _build_free_input(self, parent: ttk.Frame, pad: dict) -> None:
        ttk.Label(parent, text="送信するテキストを入力してください:",
                  font=_FONT_LABEL).pack(anchor="w", **pad)
        self._free_text = tk.Text(parent, height=6, wrap="word", font=_FONT_BASE)
        self._free_text.pack(fill="both", expand=True, **pad)
        self._free_text.bind("<Return>", self._on_free_enter)

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", **pad)
        ttk.Button(btn_frame, text="クリア", style="Big.TButton",
                   command=lambda: self._free_text.delete("1.0", "end")).pack(side="left")
        ttk.Button(btn_frame, text="ストップ", style="Big.TButton",
                   command=self._send_stop).pack(side="left", padx=(8, 0))
        ttk.Button(btn_frame, text="送信 →", style="Big.TButton",
                   command=self._send_free_text).pack(side="right")

    # ---------- 右ペイン ----------
    def _build_right(self, parent: ttk.Frame, pad: dict) -> None:
        topics = [
            ("from_human",  "/from_human",  "#e8f4e8"),
            ("to_human",    "/to_human",    "#e8e8f4"),
            ("agent_event", "/agent_event", "#f4f0e8"),
            ("stt_event",   "/stt_event",   "#f4e8f0"),
        ]
        for key, label, bg in topics:
            frame = ttk.LabelFrame(parent, text=label)
            frame.pack(fill="both", expand=True, pady=(0, 6))

            txt = tk.Text(frame, wrap="word", font=_FONT_MONO,
                          background=bg, state="disabled",
                          height=6, relief="flat")
            sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(fill="both", expand=True, padx=4, pady=4)
            self._log_texts[key] = txt

    # ------------------------------------------------------------------
    # トピック受信
    # ------------------------------------------------------------------
    def _on_topic(self, key: str, data: str) -> None:
        # JSON トピックは整形して表示
        if key in ("agent_event", "stt_event"):
            try:
                obj = json.loads(data)
                data = json.dumps(obj, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        self._root.after(0, self._append_log, key, data)

    def _append_log(self, key: str, text: str) -> None:
        widget = self._log_texts.get(key)
        if widget is None:
            return
        widget.configure(state="normal")
        # 区切り線 + タイムスタンプ + テキスト
        if widget.index("end-1c") != "1.0":
            widget.insert("end", "\n─────────────────\n")
        ts = datetime.now().strftime("%H:%M:%S")
        widget.insert("end", f"[{ts}] {text}")
        # 行数超過分を先頭から削除
        lines = int(widget.index("end-1c").split(".")[0])
        if lines > _MAX_LOG_LINES:
            widget.delete("1.0", f"{lines - _MAX_LOG_LINES}.0")
        widget.see("end")
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # コールバック
    # ------------------------------------------------------------------
    def _update_preview(self, *_) -> None:
        self._preview_var.set("".join(v.get() for v in self._selected if v.get()))

    def _clear_selection(self) -> None:
        for i, var in enumerate(self._selected):
            var.set(self._current_words[i][0] if self._current_words[i] else "")

    def _send_stop(self) -> None:
        self._publish("ストップ")

    def _send_word_selection(self) -> None:
        text = self._preview_var.get().strip()
        if text:
            self._publish(text)
            self._reshuffle_columns()

    def _on_free_enter(self, event: tk.Event) -> str:
        if not (event.state & 0x1):
            self._send_free_text()
            return "break"
        return ""

    def _send_free_text(self) -> None:
        text = self._free_text.get("1.0", "end").strip()
        if text:
            self._publish(text)
            self._free_text.delete("1.0", "end")

    def _publish(self, text: str) -> None:
        logger.info(f"[/from_human] {text}")
        self._pub.publish(String(data=text))

    # ------------------------------------------------------------------
    # メインループ
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self) -> None:
        self._root.destroy()
        if rclpy.ok():
            rclpy.shutdown()


def main() -> None:
    rclpy.init()
    node = Node("susumu_agent_gui")
    node.declare_parameter("from_human_topic", "/from_human")
    node.declare_parameter("to_human_topic", "/to_human")
    node.declare_parameter("agent_event_topic", "/agent_event")
    node.declare_parameter("stt_event_topic", "/stt_event")

    from_human_topic  = node.get_parameter("from_human_topic").value  or "/from_human"
    to_human_topic    = node.get_parameter("to_human_topic").value    or "/to_human"
    agent_event_topic = node.get_parameter("agent_event_topic").value or "/agent_event"
    stt_event_topic   = node.get_parameter("stt_event_topic").value   or "/stt_event"

    def _spin() -> None:
        with contextlib.suppress(ExternalShutdownException):
            rclpy.spin(node)

    spin_thread = threading.Thread(target=_spin, daemon=True)
    spin_thread.start()

    app = InputPanelApp(node,
                        from_human_topic=from_human_topic,
                        to_human_topic=to_human_topic,
                        agent_event_topic=agent_event_topic,
                        stt_event_topic=stt_event_topic)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)
        node.destroy_node()


if __name__ == "__main__":
    main()
