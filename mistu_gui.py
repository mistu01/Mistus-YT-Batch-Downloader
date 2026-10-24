#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mistus Batch YT Downloader — GUI (Windows)

Tkinter front-end for the yt-dlp powered engine (yt_batch_downloader_mistu.py).
NEO-BRUTALISM theme: cream background, white cards with thick black borders and
hard offset shadows, chunky uppercase headings, loud primary-color buttons with
press-down feedback. Three download modes (Default / Regular / Audio), per-item
progress bar, minute-based time inputs and a rich activity log.
Launched without a console via pythonw.exe.
"""

from __future__ import annotations

import os
import json
import queue
import re
import sys
import threading
import time
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yt_batch_downloader_mistu as engine  # noqa: E402

APP_TITLE = "Mistus Batch YT Downloader"

# --------------------------------------------------------- neo-brutal palette
BG      = "#f2ede4"   # cream window background
CARD    = "#ffffff"   # white card / white surfaces
INK     = "#100f0d"   # hard black (borders, text)
SHADOW  = "#100f0d"   # offset shadow color
ENTRY   = "#ffffff"   # input background
BORDER  = "#100f0d"   # borders

TXT     = "#100f0d"   # main text
SUB     = "#54514a"   # secondary text

YELLOW  = "#ffd23f"   # primary action
PINK    = "#ff6b9d"   # stop / destructive
LIME    = "#9cf24d"   # secondary accent
BLUE    = "#7ab8ff"   # tertiary accent
ORANGE  = "#ff9d47"
MUTED   = "#e6e0d4"   # disabled fill

BTN2    = "#ffffff"   # secondary button (white)
BTN2_H  = "#e6e0d4"   # hover
BTN3    = PINK        # stop button
BTN3_H  = "#ff8ab5"
LOG_BG  = "#100f0d"   # log = black box, neon text

FONT      = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_SM_B = ("Segoe UI", 9, "bold")
FONT_HDR  = ("Segoe UI", 18, "bold")
FONT_BIG  = ("Segoe UI", 24, "bold")
FONT_MONO = ("Consolas", 10)

OK   = "#69f0ae"
ERR  = "#ff5c5c"
WARN = "#ffd23f"
FINE = "#9aa7b4"
HEAD = "#ffd23f"

QUALITIES = ["best", "2160", "1440", "1080", "720", "480", "360", "audio"]
AUDIO_FORMATS = ["mp3", "m4a", "opus", "vorbis", "flac", "wav"]
PRESETS = ["Custom",
           "Audio M4A + thumb + meta",
           "Audio MP3 + thumb + meta",
           "Audio only (no extras)",
           "Video best"]

RE_ITEM = re.compile(r"\s*\[(\d+)/(\d+)\]")
RE_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


SH = 6          # card shadow offset
SBH = 4          # button shadow offset
BW = 3           # border thickness (cards / buttons)
EBW = 2          # border thickness (entries)


# ------------------------------------------------------------ decor ------
class Card(tk.Canvas):
    """Neo-brutal card: white face, thick black outline, hard offset shadow.
    Inner content goes into .frame."""

    def __init__(self, master, padx=18, pady=14, face=CARD):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0)
        self._padx, self._pady, self._face = padx, pady, face
        self._inner = tk.Frame(self, bg=face)
        self._win = self.create_window((padx, pady), window=self._inner,
                                       anchor="nw")
        self.frame = self._inner
        self.bind("<Configure>", self._on_canvas_cfg)
        self._inner.bind("<Configure>", self._on_inner_cfg)

    def _on_canvas_cfg(self, _event=None):
        self.after_idle(self._refresh)

    def _on_inner_cfg(self, _event=None):
        self.after_idle(self._refresh)

    def _refresh(self):
        try:
            w = self.winfo_width()
            h = max(self._inner.winfo_reqheight(), 20) + 2 * self._pady
        except Exception:
            return
        if w <= 1:
            return
        try:
            self.configure(height=h + SH)
            self._h = h + SH
            if (w, self._h) == getattr(self, "_last", None):
                return
            self._last = (w, self._h)
            self.delete("card")
            # hard offset shadow
            self.create_rectangle(SH, SH, w, h + SH - 1,
                                  fill=SHADOW, outline=SHADOW, tags="card")
            # face
            self.create_rectangle(0, 0, w - SH, h - 1,
                                  fill=self._face, outline=INK,
                                  width=BW, tags="card")
            self.coords(self._win, self._padx, self._pady)
            self.itemconfig(self._win, width=max(w - SH - 2 * self._padx, 40))
        except Exception:
            pass


class BrutButton(tk.Canvas):
    """Neo-brutal push button: loud face, thick black outline, hard shadow.
    Presses physically down onto its shadow."""

    def __init__(self, master, text, command=None, *,
                 bg=YELLOW, hover=None, fg=INK, padx=18, pady=9,
                 font=FONT_SM_B):
        try:
            parent_bg = master["bg"]
        except Exception:
            parent_bg = BG
        super().__init__(master, bg=parent_bg, highlightthickness=0,
                         bd=0, takefocus=0, cursor="hand2")
        self._text, self._command = text, command
        self._base = bg
        self._hoverc = hover or bg
        self._fg, self._padx, self._pady = fg, padx, pady
        self._font = font
        self._hover = False
        self._pressed = False
        self._disabled = False
        self._fit()
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", lambda _e: self._hover_set(True))
        self.bind("<Leave>", lambda _e: self._hover_set(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _fit(self):
        f = tkfont.Font(font=self._font)
        self.configure(width=f.measure(self._text) + 2 * self._padx,
                       height=f.metrics("linespace") + 2 * self._pady + SBH + 2)

    def _hover_set(self, flag):
        self._hover = flag
        self._draw()

    def _on_press(self, _event=None):
        self._pressed = True
        self._draw()

    def _on_release(self, _event=None):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._command and not self._disabled:
            self._command()

    def _draw(self):
        self.delete("all")
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except Exception:
            return
        if w <= 1 or h <= 1:
            self._fit()
        face = self._hoverc if (self._hover and not self._disabled) else self._base
        tcol = self._fg
        if self._disabled:
            face, tcol = MUTED, "#8a877e"
        if self._pressed and not self._disabled:
            # pressed: face drops onto the shadow line
            self.create_rectangle(0, 0, w - 1, h - SBH - 1, fill=face,
                                  outline=INK, width=BW)
            self.create_text((w - SBH) / 2, (h - SBH) / 2, text=self._text,
                             fill=tcol, font=self._font)
        else:
            self.create_rectangle(SBH, SBH, w - 1, h - 1, fill=INK,
                                  outline=INK, width=BW)
            self.create_rectangle(0, 0, w - 1 - SBH, h - 1 - SBH, fill=face,
                                  outline=INK, width=BW)
            self.create_text((w - SBH) / 2, (h - SBH) / 2, text=self._text,
                             fill=tcol, font=self._font)

    def disable(self):
        self._disabled = True
        self.configure(cursor="arrow")
        self._draw()

    def enable(self):
        self._disabled = False
        self.configure(cursor="hand2")
        self._draw()


class BrutEntry(tk.Entry):
    """Flat white input with a hard black border."""

    def __init__(self, master, var=None, width=14, **kw):
        super().__init__(master, textvariable=var, width=width,
                         bg=ENTRY, fg=INK, insertbackground=INK, bd=0,
                         relief="flat", highlightthickness=EBW,
                         highlightbackground=INK, highlightcolor=INK,
                         font=FONT_MONO, **kw)


def to_seconds(text):
    """Numeric text in minutes (or mm:ss / h:mm:ss) → seconds. Empty → None."""
    s = (text or "").strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")[:3]
        if not all(p.isdigit() for p in parts) or not parts:
            raise ValueError(s)
        secs = 0
        for p in parts:
            secs = secs * 60 + int(p)
        return int(secs)
    return int(round(float(s) * 60))


def default_dest() -> str:
    home = os.path.expanduser("~")
    base = os.path.join(home, "Downloads", "Mistus Batch YT Downloader")
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
    return base if os.path.isdir(os.path.dirname(home)) else here


class App(tk.Tk):
    def _apply_icon(self):
        """Neo-brutalist window/taskbar icon (bundled next to the script)."""
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            for cand in (os.path.join(base, "assets", "icon.ico"),
                         os.path.join(base, "icon.ico")):
                if os.path.isfile(cand):
                    self.iconbitmap(cand)
                    return
        except Exception:
            pass

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x880")
        self.minsize(960, 760)
        self.configure(bg=BG)
        self._apply_icon()

        self.msg_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.args_ns = None
        self._tl_after = None

        self._build_ui()
        self.after(120, self._poll_queue)

    # ------------------------------------------------------ widgets ------
    def _field(self, parent, label, var, width=8, note=None):
        """Vertical label-above-entry field group."""
        col = tk.Frame(parent, bg=CARD)
        tk.Label(col, text=label.upper(), bg=CARD, fg=INK, font=FONT_SM_B,
                 anchor="w").pack(fill="x")
        BrutEntry(col, var, width).pack(fill="x", pady=(3, 0))
        if note:
            tk.Label(col, text=note, bg=CARD, fg=SUB, font=FONT_SM,
                     anchor="w").pack(fill="x")
        return col

    def _check(self, parent, text, var):
        return ttk.Checkbutton(parent, text=text, variable=var,
                               style="Mist.TCheckbutton")

    def _tag(self, parent, text, bg=YELLOW):
        """Small highlighted label chip used as a section title."""
        return tk.Label(parent, text=" " + text.upper() + " ", bg=bg, fg=INK,
                        font=("Segoe UI", 10, "bold"), anchor="w")

    def _head(self, parent, title, note=None, bg=YELLOW):
        self._tag(parent, title, bg=bg).pack(anchor="w")
        if note:
            tk.Label(parent, text=note, bg=CARD, fg=SUB,
                     font=FONT_SM).pack(anchor="w", pady=(6, 2))

    # ------------------------------------------------------------ layout ---
    def _build_ui(self):
        try:
            self.tk.call("tk", "scaling", 1.2)
        except Exception:
            pass
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.selectBackground", INK)
        self.option_add("*TCombobox*Listbox.selectForeground", YELLOW)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Mist.TCheckbutton", background=CARD, foreground=INK,
                        focuscolor=CARD, relief="flat",
                        indicatorcolor=MUTED, bordercolor=INK,
                        lightcolor=INK, darkcolor=INK)
        style.map("Mist.TCheckbutton",
                  background=[("active", CARD)],
                  foreground=[("active", INK)],
                  indicatorcolor=[("selected", YELLOW),
                                  ("!selected", MUTED)])
        style.configure("Mist.TRadiobutton", background=CARD, foreground=INK,
                        focuscolor=CARD, relief="flat",
                        indicatorcolor=MUTED, bordercolor=INK,
                        lightcolor=INK, darkcolor=INK)
        style.map("Mist.TRadiobutton",
                  background=[("active", CARD)],
                  foreground=[("selected", INK), ("!selected", INK)],
                  indicatorcolor=[("selected", YELLOW),
                                  ("!selected", MUTED)])
        style.configure("Mist.Horizontal.TProgressbar",
                        troughcolor=BG, background=INK, bordercolor=INK,
                        lightcolor=INK, darkcolor=INK, thickness=18)
        style.configure("Mist.TCombobox", fieldbackground=ENTRY,
                        background=BLUE, foreground=INK, arrowcolor=INK,
                        bordercolor=INK, lightcolor=INK, darkcolor=INK)
        style.map("Mist.TCombobox",
                  fieldbackground=[("readonly", ENTRY)],
                  foreground=[("readonly", INK)])

        # --------------------------------------------------- bottom bar ---
        ctrl = tk.Frame(self, bg=BG)
        ctrl.pack(side="bottom", fill="x", padx=20, pady=(6, 16))
        self.start_btn = BrutButton(ctrl, "▶ START", self.start, bg=YELLOW,
                                    hover="#ffdc6b")
        self.start_btn.pack(side="left")
        self.stop_btn = BrutButton(ctrl, "■ STOP", self.stop, bg=BTN3,
                                   hover=BTN3_H)
        self.stop_btn.disable()
        self.stop_btn.pack(side="left", padx=12)
        BrutButton(ctrl, "📂 OPEN OUTPUT", self.open_folder,
                   bg=BTN2, hover=BTN2_H, padx=14).pack(side="left")
        BrutButton(ctrl, "⬆ UPDATE YT-DLP", self.update_ytdlp,
                   bg=LIME, hover="#b1f76e", padx=14).pack(side="left", padx=12)

        self.progress_bar = ttk.Progressbar(
            ctrl, style="Mist.Horizontal.TProgressbar", mode="determinate",
            maximum=100, value=0, length=280)
        self.progress_bar.pack(side="right", padx=(0, 14))
        self.status_var = tk.StringVar(value="IDLE")
        tk.Label(ctrl, textvariable=self.status_var, bg=BG, fg=INK,
                 font=FONT_SM_B, anchor="e")\
            .pack(side="right", fill="both", expand=True, padx=(16, 0))

        # ----------------------------------------------- activity log ---
        logcard = Card(self, pady=12)
        logcard.pack(side="bottom", fill="x", padx=20, pady=(0, 6))
        lf = logcard.frame
        head = tk.Frame(lf, bg=CARD)
        head.pack(fill="x")
        self._tag(head, "Activity", bg=BLUE).pack(side="left")
        tk.Label(head, text="timestamps • per-item progress • speed / ETA",
                 bg=CARD, fg=SUB, font=FONT_SM)\
            .pack(side="left", padx=12)
        logrow = tk.Frame(lf, bg=CARD)
        logrow.pack(fill="x", pady=(10, 0))
        self.log_text = tk.Text(logrow, height=8, wrap="word", bg=LOG_BG,
                                fg=OK, insertbackground=OK, bd=0,
                                relief="flat", highlightthickness=BW,
                                highlightbackground=INK, highlightcolor=INK,
                                font=("Consolas", 9), state="disabled",
                                padx=10, pady=8)
        sb = tk.Scrollbar(logrow, command=self.log_text.yview, bg=CARD,
                          activebackground=YELLOW, elementborderwidth=0,
                          width=12, troughcolor=CARD)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("ok", OK), ("err", ERR), ("warn", WARN),
                           ("info", FINE), ("head", HEAD)):
            self.log_text.tag_configure(tag, foreground=color)

        # ----------------------------------------- scrollable pages ---
        sbv = tk.Scrollbar(self, orient="vertical", bg=BG,
                           activebackground=YELLOW, elementborderwidth=0,
                           width=12, troughcolor=BG)
        sbv.pack(side="right", fill="y")
        scroll = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0,
                           yscrollcommand=sbv.set)
        scroll.pack(side="left", fill="both", expand=True)
        sbv.configure(command=scroll.yview)
        page = tk.Frame(scroll, bg=BG)
        page.bind("<Configure>", lambda _e: scroll.configure(
            scrollregion=scroll.bbox("all")))
        page_win = scroll.create_window((0, 0), window=page, anchor="nw")
        scroll.bind("<Configure>", lambda e: scroll.itemconfig(
            page_win, width=e.width))

        # mouse-wheel scrolling for the whole page (except text/log widgets,
        # which scroll themselves)
        def _wheel_scroll(event):
            scroll.yview_scroll(int(-event.delta / 120), "units")
            return "break"
        self._wheel_scroll = _wheel_scroll
        self._scroll_widget = scroll

        # --------------------------------------------------- header ---
        hc = Card(page, pady=14)
        hc.pack(fill="x", padx=20, pady=(18, 10))
        tk.Label(hc.frame, text=APP_TITLE.upper(), bg=CARD, fg=INK,
                 font=FONT_BIG).pack(side="left")
        self._tag(hc.frame, "YouTube batch downloader & channel scanner",
                  bg=LIME).pack(side="left", padx=14)
        self._tag(hc.frame, "engine: yt-dlp", bg=MUTED)\
            .pack(side="left", padx=(0, 14))

        # -------------------------------------------------- sources ---
        sc = Card(page)
        sc.pack(fill="x", padx=20, pady=6)
        self._head(sc.frame, "Sources",
                   "One video / playlist / channel URL per line. "
                   "Channel URLs are scanned automatically in Default mode.",
                   bg=YELLOW)
        self.url_text = tk.Text(
            sc.frame, height=5, wrap="none", bg=ENTRY, fg=INK,
            insertbackground=INK, bd=0, relief="flat",
            highlightthickness=BW, highlightbackground=INK,
            highlightcolor=INK, font=FONT_MONO,
            undo=True, padx=10, pady=8)
        self.url_text.pack(fill="x")
        brow = tk.Frame(sc.frame, bg=CARD)
        brow.pack(fill="x", pady=(12, 0))
        BrutButton(brow, "📂 LOAD TEXT FILE…", self.load_file,
                   bg=BLUE, hover="#9ccbff", padx=14).pack(side="left")
        BrutButton(brow, "CLEAR",
                   lambda: self.url_text.delete("1.0", "end"),
                   bg=BTN2, hover=BTN2_H, padx=14).pack(side="left", padx=12)
        BrutButton(brow, "🔎 SCAN REPORT", self.scan_report,
                   bg=YELLOW, hover="#ffdc6b", padx=14).pack(side="left")

        # ----------------------------------------------------- mode ---
        mc = Card(page)
        mc.pack(fill="x", padx=20, pady=6)
        self._head(mc.frame, "Download mode", bg=PINK)
        mrow = tk.Frame(mc.frame, bg=CARD)
        mrow.pack(fill="x", pady=(6, 0))
        self.mode_var = tk.StringVar(value="Default")
        for value, label in (
                ("Default", "Default  (channel scan — audio + thumbnail + text)"),
                ("Regular", "Regular  (video download)"),
                ("Audio", "Audio  (audio-only, cover art + tags)")):
            ttk.Radiobutton(mrow, text=label, variable=self.mode_var,
                            value=value, style="Mist.TRadiobutton",
                            command=self._on_mode_change)\
                .pack(side="left", padx=(0, 20))

        # audio-only extras (shown with the Audio mode)
        self.audio_frame = tk.Frame(mc.frame, bg=CARD)
        self._tag(self.audio_frame, "Audio extras • artist & song title tags",
                  bg=ORANGE).pack(anchor="w", pady=(12, 2))
        arow = tk.Frame(self.audio_frame, bg=CARD)
        arow.pack(fill="x")
        tk.Label(arow, text="ARTIST:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.artist_var = tk.StringVar(value="")
        BrutEntry(arow, self.artist_var, 26).pack(side="left", padx=(6, 22))
        tk.Label(arow, text="SONG TITLE:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.songtitle_var = tk.StringVar(value="")
        BrutEntry(arow, self.songtitle_var, 34).pack(side="left", padx=(6, 0))

        # scan-only options (shown with Default mode)
        self.scan_opts = tk.Frame(mc.frame, bg=CARD)
        srow = tk.Frame(self.scan_opts, bg=CARD)
        srow.pack(fill="x", pady=(12, 0))
        self.shorts_var = tk.BooleanVar(value=False)
        self._check(srow, "Include Shorts", self.shorts_var).pack(side="left")
        self.forcescan_var = tk.BooleanVar(value=False)
        self._check(srow, "Force scan all URLs", self.forcescan_var)\
            .pack(side="left", padx=(18, 0))

        self._on_mode_change()

        # ------------------------------------------- download options ---
        oc = Card(page)
        oc.pack(fill="x", padx=20, pady=6)
        self._head(oc.frame, "Output & options",
                   "cookies: a cookies.txt file, or a browser name for its "
                   "LIVE cookies — 'firefox' works best; new Chrome blocks "
                   "automated decryption (app-bound encryption), the app will "
                   "tell you and continue without cookies. Multi-profile: "
                   "'chrome:Profile 2' / 'chrome:Work' / 'chrome:2'", bg=BLUE)

        r1 = tk.Frame(oc.frame, bg=CARD)
        r1.pack(fill="x", pady=(8, 0))
        tk.Label(r1, text="SAVE TO:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.dest_var = tk.StringVar(value=default_dest())
        BrutEntry(r1, self.dest_var, 40).pack(side="left", fill="x",
                                              expand=True, padx=(6, 8))
        BrutButton(r1, "…", self.browse_dest, bg=BTN2, hover=BTN2_H,
                   padx=10).pack(side="left")
        tk.Label(r1, text="QUALITY:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left", padx=(18, 0))
        self.quality_var = tk.StringVar(value="audio")
        self.quality_cb = ttk.Combobox(
            r1, textvariable=self.quality_var, values=QUALITIES,
            state="readonly", width=8,
            style="Mist.TCombobox")
        self.quality_cb.pack(side="left", padx=(6, 0))
        tk.Label(r1, text="AUDIO FMT:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left", padx=(18, 0))
        self.fmt_var = tk.StringVar(value="mp3")
        self.fmt_cb = ttk.Combobox(
            r1, textvariable=self.fmt_var, values=AUDIO_FORMATS,
            state="readonly", width=6,
            style="Mist.TCombobox")
        self.fmt_cb.pack(side="left", padx=(6, 0))

        r2 = tk.Frame(oc.frame, bg=CARD)
        r2.pack(fill="x", pady=(14, 0))
        self.delay_var = tk.StringVar(value="3")
        self._field(r2, "Delay between items (sec)", self.delay_var, 8,
                    note="safe: 2-3 sec")\
            .pack(side="left", padx=(0, 16))
        self.timelimit_var = tk.StringVar(value="")
        self._field(r2, "Time limit (minutes)", self.timelimit_var, 8,
                    note="0 = unlimited")\
            .pack(side="left", padx=(0, 16))
        self.minlen_var = tk.StringVar(value="")
        self._field(r2, "Min video length (minutes)", self.minlen_var, 8,
                    note="scan mode")\
            .pack(side="left", padx=(0, 16))
        self.maxlen_var = tk.StringVar(value="")
        self._field(r2, "Max video length (minutes)", self.maxlen_var, 8,
                    note="scan mode").pack(side="left", padx=(0, 16))
        self.limit_var = tk.StringVar(value="0")
        self._field(r2, "Playlist limit", self.limit_var, 6,
                    note="0 = all").pack(side="left", padx=(0, 16))
        self.jobs_var = tk.StringVar(value="1")
        self._field(r2, "Jobs", self.jobs_var, 5, note="1-8")\
            .pack(side="left", padx=(0, 16))
        self.stalltimeout_var = tk.StringVar(value="5")
        self._field(r2, "Stall timeout (min)", self.stalltimeout_var, 6,
                    note="skip if stuck (0=off)")\
            .pack(side="left")

        r3 = tk.Frame(oc.frame, bg=CARD)
        r3.pack(fill="x", pady=(14, 0))
        tk.Label(r3, text="COOKIES:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.cookies_var = tk.StringVar(value="")
        BrutEntry(r3, self.cookies_var, 40).pack(side="left", fill="x",
                                                 expand=True, padx=(6, 8))
        BrutButton(r3, "…", self.browse_cookies, bg=BTN2, hover=BTN2_H,
                   padx=10).pack(side="left")

        # --------------------------------------------------- sessions ---
        sesc = Card(page)
        sesc.pack(fill="x", padx=20, pady=6)
        self._head(sesc.frame, "Sessions",
                   "Auto-saved as \u201clast session\u201d on exit and restored "
                   "on start. Save named sessions to switch between "
                   "video / playlist / music projects.", bg=ORANGE)
        srow = tk.Frame(sesc.frame, bg=CARD)
        srow.pack(fill="x", pady=(8, 2))
        tk.Label(srow, text="SAVE AS:", bg=CARD, fg=INK, font=FONT_SM_B)\
            .pack(side="left")
        self.session_name_var = tk.StringVar(value="")
        BrutEntry(srow, self.session_name_var, 18).pack(side="left",
                                                        padx=(6, 12))
        BrutButton(srow, "💾 SAVE SESSION", self.save_session, bg=LIME,
                   hover="#b1f76e", padx=14).pack(side="left")
        tk.Label(srow, text="SAVED:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left", padx=(16, 0))
        self.session_pick_var = tk.StringVar(value="")
        self.session_cb = ttk.Combobox(srow, textvariable=self.session_pick_var,
                                       values=self._list_sessions(),
                                       state="readonly", width=20,
                                       style="Mist.TCombobox")
        self.session_cb.pack(side="left", padx=(6, 10))
        BrutButton(srow, "♻ LOAD", self.load_session, bg=BLUE,
                   hover="#9ccbff", padx=12).pack(side="left")
        BrutButton(srow, "🗑 DELETE", self.delete_session, bg=BTN3,
                   hover=BTN3_H, padx=12).pack(side="left", padx=(10, 0))

        # --------------------------------------------------- advanced ---
        ac = Card(page)
        ac.pack(fill="x", padx=20, pady=(6, 24))
        self._head(ac.frame, "Advanced", bg=LIME)
        a1 = tk.Frame(ac.frame, bg=CARD)
        a1.pack(fill="x", pady=(8, 0))
        self.subs_var = tk.BooleanVar(value=False)
        self._check(a1, "Subtitles", self.subs_var).pack(side="left")
        tk.Label(a1, text="LANGS:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left", padx=(6, 0))
        self.subslangs_var = tk.StringVar(value="en.*")
        BrutEntry(a1, self.subslangs_var, 10).pack(side="left", padx=(4, 16))
        self.nothumb_var = tk.BooleanVar(value=True)
        self._check(a1, "No thumbnail", self.nothumb_var)\
            .pack(side="left", padx=(0, 16))
        self.nometa_var = tk.BooleanVar(value=True)
        self._check(a1, "No metadata", self.nometa_var)\
            .pack(side="left", padx=(0, 16))
        self.noplaylist_var = tk.BooleanVar(value=False)
        self._check(a1, "Single video only", self.noplaylist_var)\
            .pack(side="left", padx=(0, 16))
        self.keepdupes_var = tk.BooleanVar(value=False)
        self._check(a1, "Keep dupes", self.keepdupes_var).pack(side="left")

        a2 = tk.Frame(ac.frame, bg=CARD)
        a2.pack(fill="x", pady=(12, 0))
        self.noarchive_var = tk.BooleanVar(value=False)
        self._check(a2, "No archive", self.noarchive_var).pack(side="left")
        self.redo_var = tk.BooleanVar(value=False)
        self._check(a2, "Redo (ignore archive)", self.redo_var)\
            .pack(side="left", padx=(16, 0))
        self.verbose_var = tk.BooleanVar(value=False)
        self._check(a2, "Verbose yt-dlp output", self.verbose_var)\
            .pack(side="left", padx=(16, 0))
        tk.Label(a2, text="RETRIES:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left", padx=(16, 0))
        self.retries_var = tk.StringVar(value="10")
        BrutEntry(a2, self.retries_var, 5).pack(side="left", padx=(6, 16))
        tk.Label(a2, text="FORMAT OVERRIDE:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.format_var = tk.StringVar(value="")
        BrutEntry(a2, self.format_var, 20).pack(side="left", padx=(6, 16))
        tk.Label(a2, text="PRESET:", bg=CARD, fg=INK,
                 font=FONT_SM_B).pack(side="left")
        self.preset_var = tk.StringVar(value="Custom")
        p_cb = ttk.Combobox(a2, textvariable=self.preset_var, values=PRESETS,
                            state="readonly", width=22, style="Mist.TCombobox")
        p_cb.pack(side="left", padx=(6, 0))
        p_cb.bind("<<ComboboxSelected>>", self._apply_preset)

        self._bind_wheel()
        self._restore_last_session()

    # ------------------------------------------------- wheel rebinding ---
    def _bind_wheel(self):
        """(Re)bind the mouse wheel over every page child; call after layout
        changes (startup, mode switches) so late-packed widgets get it too."""
        scroll = self._scroll_widget

        def bind_wheel(w):
            if isinstance(w, (tk.Text, tk.Scrollbar, ttk.Combobox)):
                return
            try:
                w.bind("<MouseWheel>", self._wheel_scroll)
            except Exception:
                return
            for child in w.winfo_children():
                bind_wheel(child)
        bind_wheel(scroll)

    # ------------------------------------------------------ mode switch ---
    def _on_mode_change(self):
        mode = self.mode_var.get()
        # Audio mode = the best-audio system: quality & format are decided
        # by the engine (best stream -> mp3 @ 320), so the combos rest.
        if hasattr(self, "quality_cb"):
            self.quality_cb.configure(
                state="disabled" if mode == "Audio" else "readonly")
        if hasattr(self, "fmt_cb"):
            self.fmt_cb.configure(
                state="disabled" if mode == "Audio" else "readonly")
        if mode == "Audio":
            self.audio_frame.pack(fill="x", pady=(6, 0))
            self.scan_opts.pack_forget()
        else:
            self.audio_frame.pack_forget()
            if mode == "Default":
                self.scan_opts.pack(fill="x", pady=(6, 0))
            else:
                self.scan_opts.pack_forget()
        if hasattr(self, "_wheel_scroll"):
            self._bind_wheel()

    # ------------------------------------------------------ sessions -----
    def _app_dir(self) -> str:
        """%APPDATA%\\MistusBatchYTDownloader — survives app updates."""
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "MistusBatchYTDownloader")
        os.makedirs(d, exist_ok=True)
        return d

    def _sessions_dir(self) -> str:
        d = os.path.join(self._app_dir(), "sessions")
        os.makedirs(d, exist_ok=True)
        return d

    def _last_session_path(self) -> str:
        return os.path.join(self._app_dir(), "last_session.json")

    def _list_sessions(self) -> list:
        try:
            return sorted(f[:-5] for f in os.listdir(self._sessions_dir())
                          if f.endswith(".json"))
        except Exception:
            return []

    def _capture_state(self) -> dict:
        """Every knob that defines a session."""
        return {
            "mode": self.mode_var.get(),
            "urls": self.url_text.get("1.0", "end").rstrip("\n"),
            "artist": self.artist_var.get(),
            "song": self.songtitle_var.get(),
            "shorts": self.shorts_var.get(),
            "forcescan": self.forcescan_var.get(),
            "dest": self.dest_var.get(),
            "quality": self.quality_var.get(),
            "audio_fmt": self.fmt_var.get(),
            "delay": self.delay_var.get(),
            "timelimit": self.timelimit_var.get(),
            "minlen": self.minlen_var.get(),
            "maxlen": self.maxlen_var.get(),
            "limit": self.limit_var.get(),
            "jobs": self.jobs_var.get(),
            "stalltimeout": self.stalltimeout_var.get(),
            "cookies": self.cookies_var.get(),
            "subs": self.subs_var.get(),
            "subslangs": self.subslangs_var.get(),
            "nothumb": self.nothumb_var.get(),
            "nometa": self.nometa_var.get(),
            "noplaylist": self.noplaylist_var.get(),
            "keepdupes": self.keepdupes_var.get(),
            "noarchive": self.noarchive_var.get(),
            "redo": self.redo_var.get(),
            "verbose": self.verbose_var.get(),
            "retries": self.retries_var.get(),
            "format": self.format_var.get(),
        }

    def _apply_state(self, st: dict) -> bool:
        if not st:
            return False
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", st.get("urls", ""))
        self.mode_var.set(st.get("mode", "Default"))
        self.artist_var.set(st.get("artist", ""))
        self.songtitle_var.set(st.get("song", ""))
        self.shorts_var.set(bool(st.get("shorts", False)))
        self.forcescan_var.set(bool(st.get("forcescan", False)))
        dest = st.get("dest", "")
        if dest and os.path.isdir(dest):
            self.dest_var.set(dest)
        if st.get("quality") in QUALITIES:
            self.quality_var.set(st["quality"])
        if st.get("audio_fmt") in AUDIO_FORMATS:
            self.fmt_var.set(st["audio_fmt"])
        for var, key in ((self.delay_var, "delay"), (self.timelimit_var, "timelimit"),
                         (self.minlen_var, "minlen"), (self.maxlen_var, "maxlen"),
                         (self.limit_var, "limit"), (self.jobs_var, "jobs"),
                         (self.stalltimeout_var, "stalltimeout"),
                         (self.subslangs_var, "subslangs"), (self.retries_var, "retries"),
                         (self.format_var, "format"), (self.cookies_var, "cookies")):
            var.set(str(st.get(key, "")) if key in st else var.get())
        for wvar, key in ((self.subs_var, "subs"), (self.nothumb_var, "nothumb"),
                          (self.nometa_var, "nometa"), (self.noplaylist_var, "noplaylist"),
                          (self.keepdupes_var, "keepdupes"), (self.noarchive_var, "noarchive"),
                          (self.redo_var, "redo"), (self.verbose_var, "verbose")):
            wvar.set(bool(st.get(key, wvar.get())))
        self.preset_var.set("Custom")
        self._on_mode_change()
        return True

    def _save_state_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self._capture_state(), fh, ensure_ascii=False, indent=1)

    def save_session(self):
        name = self.session_name_var.get().strip()
        if not name:
            name = self.session_pick_var.get().strip() or "session"
        safe = name.replace("<", "_").replace(">", "_").replace(":", "_")\
                   .replace('"', "_").replace("/", "_").replace("\\", "_")\
                   .replace("|", "_").replace("?", "_").replace("*", "_").strip()
        path = os.path.join(self._sessions_dir(), (safe or "session") + ".json")
        try:
            self._save_state_file(path)
            self._log(None, "head", f"💾 session saved: {safe}")
        except Exception as exc:
            self._log(None, "err", f"session save failed: {exc}")
            return
        self.session_cb.configure(values=self._list_sessions())
        self.session_pick_var.set(safe)
        self.session_name_var.set(safe)

    def load_session(self):
        name = self.session_pick_var.get().strip()
        if not name:
            self._log(None, "warn", "pick a saved session from the list first")
            return
        try:
            with open(os.path.join(self._sessions_dir(), name + ".json"),
                      "r", encoding="utf-8") as fh:
                st = json.load(fh)
        except Exception as exc:
            self._log(None, "err", f"session load failed: {exc}")
            return
        self._apply_state(st)
        self.session_name_var.set(name)
        self._log(None, "head", f"♻ session loaded: {name}")

    def delete_session(self):
        name = self.session_pick_var.get().strip()
        if not name:
            return
        if not messagebox.askyesno(APP_TITLE, f'Delete saved session "{name}"?'):
            return
        try:
            os.remove(os.path.join(self._sessions_dir(), name + ".json"))
            self.session_pick_var.set("")
            self.session_cb.configure(values=self._list_sessions())
            self._log(None, "info", f"🗑 session deleted: {name}")
        except Exception as exc:
            self._log(None, "err", f"session delete failed: {exc}")

    def _autosave(self):
        try:
            self._save_state_file(self._last_session_path())
        except Exception:
            pass

    def _restore_last_session(self):
        try:
            with open(self._last_session_path(), "r", encoding="utf-8") as fh:
                st = json.load(fh)
        except Exception:
            return
        if self._apply_state(st):
            self._log(None, "head", "♻ last session restored "
                       "(auto-saved when the app was closed)")
            self._log(None, "info",
                      "· links, cookies, settings & download location back")

    # ----------------------------------------------------------- actions ---
    def load_file(self):
        path = filedialog.askopenfilename(
            title="Select URL list", filetypes=[("Text files", "*.txt"),
                                                ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                data = fh.read()
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Cannot read file:\n{exc}")
            return
        lines = [ln.strip() for ln in data.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.url_text.insert("end", "\n".join(lines) + "\n")

    def browse_dest(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.dest_var.set(path)
            for sub in ("Audio", "Thumbnail", "Text File"):
                try:
                    os.makedirs(os.path.join(path, sub), exist_ok=True)
                except OSError:
                    pass

    def browse_cookies(self):
        path = filedialog.askopenfilename(
            title="Select cookies.txt (Netscape format)",
            filetypes=[("Text files (*.txt)", "*.txt"), ("All files (*.*)", "*.*")])
        if path:
            self.cookies_var.set(path)

    def _apply_preset(self, _event=None):
        p = self.preset_var.get()
        if p == "Audio M4A + thumb + meta":
            self.mode_var.set("Audio")
            self.quality_var.set("audio")
            self.fmt_var.set("m4a")
            self.nothumb_var.set(False)
            self.nometa_var.set(False)
        elif p == "Audio MP3 + thumb + meta":
            self.mode_var.set("Audio")
            self.quality_var.set("audio")
            self.fmt_var.set("mp3")
            self.nothumb_var.set(False)
            self.nometa_var.set(False)
        elif p == "Audio only (no extras)":
            self.mode_var.set("Audio")
            self.quality_var.set("audio")
            self.fmt_var.set("mp3")
            self.nothumb_var.set(True)
            self.nometa_var.set(True)
        elif p == "Video best":
            self.mode_var.set("Regular")
            self.quality_var.set("best")
            self.nothumb_var.set(True)
            self.nometa_var.set(True)
        self._on_mode_change()

    def open_folder(self):
        dest = self.dest_var.get().strip() or default_dest()
        try:
            os.makedirs(dest, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(dest)  # type: ignore[attr-defined]  # noqa: S606
            else:
                messagebox.showinfo(APP_TITLE,
                                    "Opening folders is supported on Windows only.")
        except Exception as exc:  # pragma: no cover
            messagebox.showerror(APP_TITLE, f"Could not open folder:\n{exc}")

    # ------------------------------------------------------- scan report ---
    def scan_report(self):
        """Dry-run scan: report channel/playlist contents, no downloads."""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Already running — use Stop first.")
            return
        raw_lines = [ln.strip() for ln
                     in self.url_text.get("1.0", "end").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        targets = [engine.clean_url(ln) for ln in raw_lines if engine.clean_url(ln)]
        if not targets:
            messagebox.showwarning(APP_TITLE, "Enter at least one URL or a channel.")
            return

        ns = engine.parse_args([""])
        ns.targets = targets
        raw_cookie = self.cookies_var.get().strip().strip("'\"")
        ns.cookies = os.path.normpath(raw_cookie) if raw_cookie else None
        ns.shorts = self.shorts_var.get()
        try:
            ns.min_length = to_seconds(self.minlen_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE,
                                 "Min length must look like '2' or '2:30' (minutes).")
            return
        try:
            ns.max_length = to_seconds(self.maxlen_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE,
                                 "Max length must look like '8' or '8:00' (minutes).")
            return
        try:
            ns.playlist_limit = max(0, int(self.limit_var.get() or 0))
        except ValueError:
            messagebox.showerror(APP_TITLE, "Limit must be a number.")
            return
        ns.verbose = self.verbose_var.get()

        engine.reset_cancel()
        self.args_ns = ns
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        _filter = ""
        if ns.min_length is not None or ns.max_length is not None:
            lo = self.minlen_var.get().strip() or "any"
            hi = self.maxlen_var.get().strip() or "any"
            _filter = f"  •  length {lo}-min … {hi}-min"
        self._log(None, "head",
                  f"🔎 scan report  •  sources={len(targets)}{_filter}"
                  f"{'  •  +shorts' if ns.shorts else ''}"
                  f"{'  •  cookies' if ns.cookies else ''}")
        self.start_btn.disable()
        self.stop_btn.enable()
        self.progress_bar.configure(value=0)
        self.status_var.set("scanning (report only)…")
        self.worker = threading.Thread(target=self._scan_worker, daemon=True)
        self.worker.start()

    def _scan_worker(self):
        q = self.msg_q
        engine.set_logger(lambda m: q.put(m))
        try:
            rc = engine.scan_report_pipeline(self.args_ns)
            q.put(f"@done:{rc}")
        except Exception:
            err = "".join(traceback.format_exc(limit=8))
            q.put("! unexpected error:\n" + err)
            q.put("@done:1")
        finally:
            engine.set_logger(None)

    # ------------------------------------------------------------- start ---
    def start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Already running — use Stop first.")
            return
        raw_lines = [ln.strip() for ln
                     in self.url_text.get("1.0", "end").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        targets = [engine.clean_url(ln) for ln in raw_lines if engine.clean_url(ln)]
        if not targets:
            messagebox.showwarning(APP_TITLE, "Enter at least one URL or a channel.")
            return

        ns = engine.parse_args([""])
        ns.targets = targets
        ns.dest = self.dest_var.get().strip() or default_dest()

        _mode = self.mode_var.get()
        ns.regular = (_mode == "Regular")
        ns.music = (_mode == "Audio")
        ns.scan = False
        ns.mode = {"Default": None, "Regular": "regular", "Audio": "music"}[_mode]

        ns.audio_format = self.fmt_var.get()
        ns.quality = self.quality_var.get()
        if ns.music:
            ns.audio_format = "mp3"      # best-audio system output is mp3 @ 320

        try:
            ns.time_limit = float(self.timelimit_var.get().strip() or 0)
            if ns.time_limit < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE,
                                 "Time limit must be a number of minutes (or empty).")
            return
        try:
            ns.min_length = to_seconds(self.minlen_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE,
                                 "Min length must look like '2' or '2:30' (minutes).")
            return
        try:
            ns.max_length = to_seconds(self.maxlen_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE,
                                 "Max length must look like '8' or '8:00' (minutes).")
            return
        try:
            ns.playlist_limit = max(0, int(self.limit_var.get() or 0))
        except ValueError:
            messagebox.showerror(APP_TITLE, "Limit must be a number.")
            return
        try:
            ns.scan_delay = max(0.0, float(self.delay_var.get() or 0))
        except ValueError:
            messagebox.showerror(APP_TITLE, "Delay must be a number (seconds).")
            return
        try:
            ns.jobs = max(1, min(8, int(self.jobs_var.get() or 1)))
        except ValueError:
            ns.jobs = 1
        try:
            ns.stall_timeout = max(0.0, float(self.stalltimeout_var.get().strip() or 5) * 60)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Stall timeout must be a number of minutes.")
            return
        raw_cookie = self.cookies_var.get().strip().strip("'\"")
        ns.cookies = os.path.normpath(raw_cookie) if raw_cookie else None
        ns.subs = self.subs_var.get()
        ns.subs_langs = self.subslangs_var.get().strip() or "en.*"
        ns.no_thumb = self.nothumb_var.get()
        ns.no_meta = self.nometa_var.get()
        ns.no_playlist = self.noplaylist_var.get()
        ns.keep_dupes = self.keepdupes_var.get()
        ns.no_archive = self.noarchive_var.get()
        ns.redo = self.redo_var.get()
        ns.verbose = self.verbose_var.get()
        try:
            ns.retries = max(1, int(self.retries_var.get() or 10))
        except ValueError:
            ns.retries = 10
        ns.format = self.format_var.get().strip() or None
        ns.artist = self.artist_var.get().strip() or None
        ns.song_title = self.songtitle_var.get().strip() or None
        if ns.no_archive or ns.redo:
            ns.archive = None
        else:
            ns.archive = os.path.join(ns.dest, "downloaded.txt")

        engine.reset_cancel()
        self.args_ns = ns
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._log(None, "head",
                  f"▶ start  •  mode={_mode}  quality={ns.quality}"
                  f"/{ns.audio_format or '-'}  items={len(targets)}"
                  f"  jobs={ns.jobs}")
        self._log(None, "info", f"destination: {ns.dest}")
        if ns.archive and not ns.no_archive:
            self._log(None, "info",
                      f"archive: {ns.archive} (skipping already-downloaded)")
        if ns.time_limit > 0:
            self._log(None, "info",
                      f"time limit: {ns.time_limit:g} min"
                      " — engine will stop when reached")
            self._tl_after = self.after(int(ns.time_limit * 60 * 1000),
                                        self._time_limit_reached)

        self.start_btn.disable()
        self.stop_btn.enable()
        self.progress_bar.configure(value=0)
        self.status_var.set("RUNNING…")
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def _time_limit_reached(self):
        if self.worker and self.worker.is_alive():
            engine.request_cancel()
            self.status_var.set("time limit reached — stopping…")
            self._log(None, "warn", "⏱  time limit reached — stopping "
                                    "after the current item…")

    def stop(self):
        engine.request_cancel()
        self.status_var.set("stopping…")

    def update_ytdlp(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Already running — wait for it to finish.")
            return
        engine.reset_cancel()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.start_btn.disable()
        self.stop_btn.disable()
        self.status_var.set("updating yt-dlp…")
        self.worker = threading.Thread(target=self._update_worker, daemon=True)
        self.worker.start()

    def _update_worker(self):
        q = self.msg_q
        engine.set_logger(lambda m: q.put(m))
        try:
            ok = engine.update_ytdlp()
            q.put("@done:" + ("0" if ok else "1"))
        except Exception:
            err = "".join(traceback.format_exc(limit=8))
            q.put("! unexpected error:\n" + err)
            q.put("@done:1")
        finally:
            engine.set_logger(None)

    def _worker(self):
        q = self.msg_q
        engine.set_logger(lambda m: q.put(m))
        rc = 0
        try:
            rc = engine.execute(self.args_ns)
            q.put(f"@done:{rc}")
        except Exception:
            err = "".join(traceback.format_exc(limit=8))
            q.put("! unexpected error:\n" + err)
            q.put("@done:1")
        finally:
            engine.set_logger(None)

    # -------------------------------------------------------------- poll ---
    def _poll_queue(self):
        try:
            for _ in range(300):
                m = self.msg_q.get_nowait()
                if m.startswith("@done:"):
                    self._big_finish(m.split(":", 1)[1])
                else:
                    self._log(None, self._classify(m), m)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _big_finish(self, rc):
        if self._tl_after is not None:
            try:
                self.after_cancel(self._tl_after)
            except Exception:
                pass
            self._tl_after = None
        self.start_btn.enable()
        self.stop_btn.disable()
        if rc == "0":
            self.status_var.set("FINISHED ✔")
            self._log(None, "head", "✔ finished")
        elif rc == "130":
            self.status_var.set("STOPPED BY USER")
            self._log(None, "warn", "✋ stopped by user — partial results kept")
        elif rc == "2":
            self.status_var.set("INPUT ERROR")
        else:
            self.status_var.set(f"finished with failures (code {rc})")
        self.progress_bar.configure(value=0)
        self.log_text.configure(state="disabled")

    @staticmethod
    def _classify(msg: str) -> str:
        if "✗" in msg or "FAILED" in msg or ("error" in msg.lower()
                                             and "not a bot" not in msg):
            return "err"
        if "✓" in msg or "✔" in msg:
            return "ok"
        if "⚠" in msg or "stalled" in msg.lower() or msg.startswith("!") or "hint" in msg:
            return "warn"
        return "info"

    # -------------------------------------------------------- progress bar ---
    def _maybe_progress(self, text: str) -> None:
        im = RE_ITEM.search(text)
        pm = RE_PCT.search(text)
        if im:
            idx, total = int(im.group(1)), int(im.group(2))
            if pm:
                pct = min(100.0, max(0.0, float(pm.group(1))))
                overall = ((idx - 1) + pct / 100.0) / max(1, total) * 100.0
                try:
                    self.progress_bar.configure(value=overall)
                except Exception:
                    pass
                self.status_var.set(f"item {idx}/{total}  •  {pct:.1f}%")
            else:
                self.status_var.set(f"item {idx}/{total} …")

    # ---------------------------------------------------------- log sink ---
    def _log(self, tag, cls=None, text=""):
        tag = tag or cls or "info"
        try:
            self._maybe_progress(text)
        except Exception:
            pass
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {text}\n", tag)
        if self.log_text.index("end-1c") != "1.0":
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_close(self):
        self._autosave()
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                    APP_TITLE, "A download is running. Stop it and exit?"):
                return
            engine.request_cancel()
        self.destroy()


def main() -> int:
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
