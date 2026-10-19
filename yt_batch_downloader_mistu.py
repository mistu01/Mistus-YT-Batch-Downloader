#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YT-Batch-Downloader-Mistu  —  YouTube batch downloader (CLI)

Core engine: yt-dlp (https://github.com/yt-dlp/yt-dlp).
Designed to ship as a fully portable bundle: embedded Python + yt-dlp + FFmpeg.
No installation required — the build script produces a self-contained zip.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutTimeout  # noqa: F401 (reserved)
from urllib.parse import urlparse
import urllib.request

__version__ = "2.6.0"
APP_NAME = "Mistus Batch YT Downloader"

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    sys.stderr.write(
        f"{APP_NAME}: the 'yt-dlp' package is required.\n"
        "  pip install yt-dlp\n"
    )
    raise SystemExit(2)

try:
    from yt_dlp.postprocessor.common import PostProcessor as _BasePP
except Exception:  # pragma: no cover
    _BasePP = object


class _SetMusicMetaPP(_BasePP):
    """Post-processor that writes final audio tags:
    artist  = user-entered artist, else channel/uploader
    title   = user-entered song title, else the video title."""

    def __init__(self, downloader, artist=None, title=None):
        super().__init__(downloader)
        self._artist = artist
        self._title = title

    def run(self, info):
        artist = (self._artist
                  or info.get("channel")
                  or info.get("uploader")
                  or info.get("creator")
                  or info.get("uploader_id")
                  or "Unknown Artist")
        info["artist"] = artist
        info["artists"] = [artist]
        info["creator"] = artist
        info["album_artist"] = artist
        info["track"] = self._title or info.get("track") or info.get("title") or "Unknown Title"
        if self._title:
            info["title"] = self._title
        return [], info

# ---------------------------------------------------------------- console ---
PRINT_LOCK = threading.Lock()
_LOG = None                       # injectable logger (GUI uses a queue sink)
_CANCEL_LATCH = threading.Event()  # cooperative stop flag


class RunCancelled(Exception):
    """Raised inside the pipeline when the user pressed Stop."""


def set_logger(fn) -> None:
    """GUIs install a log sink: log lines go to fn(msg) instead of stdout."""
    global _LOG
    _LOG = fn


def request_cancel() -> None:
    """Ask the running pipeline to stop after the current download."""
    _CANCEL_LATCH.set()


def reset_cancel() -> None:
    _CANCEL_LATCH.clear()


def is_cancelled() -> bool:
    return _CANCEL_LATCH.is_set()


def _check_cancel() -> None:
    if _CANCEL_LATCH.is_set():
        raise RunCancelled()


def _force_utf8_stdio() -> None:
    """Make sure we can print unicode symbols on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def term_width(default: int = 100) -> int:
    try:
        return max(20, shutil.get_terminal_size((default, 24)).columns - 1)
    except Exception:
        return default


def log(msg: str = "") -> None:
    with PRINT_LOCK:
        if _LOG is not None:
            try:
                _LOG(msg)
            except Exception:
                pass
            return
        try:
            print(msg, flush=True)
        except Exception:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def human_size(n) -> str:
    if not n:
        return "?"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TiB"


def human_time(seconds) -> str:
    if seconds is None:
        return "?"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "?"
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ------------------------------------------------------------- arguments ----
EXAMPLES = """\
examples:
  %(prog)s https://www.youtube.com/watch?v=dQw4w9WgXcQ
  %(prog)s -q 1080 -d "D:/Media/Songs" urls.txt
  %(prog)s -j 3 --no-playlist -q 720 url1 url2 url3
  %(prog)s -q audio --audio-format mp3 --playlist-limit 15 "https://www.youtube.com/playlist?list=PL..."
  %(prog)s -q 1080 --subs --subs-langs "en.*,hi" list.txt
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "YouTube batch downloader powered by yt-dlp.\n"
            "Pass one or more URLs (or a .txt file with one URL per line)."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "targets", nargs="*", metavar="URL|FILE",
        help="video/playlist URL(s), or a text file with one URL per line "
             "(lines starting with '#' are ignored)",
    )
    out = parser.add_argument_group("output")
    out.add_argument("-d", "--dest", default="downloads", metavar="DIR",
                     help='destination folder (default: "downloads")')
    out.add_argument("-q", "--quality",
                     choices=["best", "2160", "1440", "1080", "720", "480", "360", "audio"],
                     default="best",
                     help="max video height / 'audio' for audio-only (default: best)")
    out.add_argument("--audio-format", choices=["mp3", "m4a", "opus", "vorbis", "flac", "wav"],
                     default=None, metavar="FMT",
                     help="audio container when -q audio is used (default: mp3)")

    scope = parser.add_argument_group("scope")
    scope.add_argument("--scan", action="store_true",
                       help="force channel-scan mode (default behaviour for channel "
                            "URLs like youtube.com/@name): scrape every long video "
                            "and save its audio, thumbnail and an info .txt file")
    scope.add_argument("--regular", action="store_true",
                       help="regular mode: download the given video(s)/playlist(s) only; "
                            "never scan a whole channel (thumbnail/text info off by default)")
    scope.add_argument("--mode", choices=["scan", "regular", "music"], default=None,
                        help="download mode: scan (channel scan), regular (batch), or music")
    scope.add_argument("--shorts", action="store_true",
                       help="scan mode: also include the channel's Shorts")
    scope.add_argument("--min-length", default=None, metavar="LEN",
                       help='scan mode: only videos at least LEN long ("90", "2:30", "1:02:00")')
    scope.add_argument("--max-length", default=None, metavar="LEN",
                       help="scan mode: only videos at most LEN long")
    scope.add_argument("--scan-delay", type=float, default=3.0, metavar="SEC",
                       help="scan mode: pause between videos to avoid bot-rate-limits "
                            "(default: 3 — safe delay; 0 = no pause)")
    scope.add_argument("--no-playlist", action="store_true",
                       help="if a URL points to both a video and a playlist, download only the video")
    scope.add_argument("--single", dest="no_playlist", action="store_true",
                       help="alias for --no-playlist: download only the single video, ignore any playlist")
    scope.add_argument("--playlist-limit", type=int, default=0, metavar="N",
                       help="download at most N entries from a playlist (0 = all)")
    scope.add_argument("--keep-dupes", action="store_true",
                       help="do not remove duplicate URLs from the input")

    resume = parser.add_argument_group("resume / archive")
    resume.add_argument("--archive", default=None, metavar="FILE",
                        help=r"download history file (default: <dest>\downloaded.txt); "
                             "already-listed videos are skipped")
    resume.add_argument("--no-archive", action="store_true",
                        help="do not use a download archive at all")
    resume.add_argument("--redo", action="store_true",
                        help="ignore the archive for this run (re-download everything)")

    media = parser.add_argument_group("media extras")
    media.add_argument("--subs", action="store_true",
                       help="also download subtitles")
    media.add_argument("--subs-langs", default="en.*", metavar="LANGS",
                       help='subtitle languages, comma separated (default: "en.*")')
    media.add_argument("--no-thumb", action="store_true",
                       help="do not embed the thumbnail into the file")
    media.add_argument("--no-meta", action="store_true",
                       help="do not embed metadata (title, tags, chapters)")
    media.add_argument("--music", action="store_true",
                       help="music mode: best audio -> m4a, embed cover art + metadata, "
                            "tag artist/title from --artist/--song-title")
    media.add_argument("--artist", default=None, metavar="NAME",
                       help="artist name for music mode (overrides metadata)")
    media.add_argument("--song-title", "--title", dest="song_title", default=None,
                       metavar="TITLE",
                       help="song title for music mode (overrides metadata)")

    engine = parser.add_argument_group("engine")
    engine.add_argument("-j", "--jobs", type=int, default=1, metavar="N",
                        help="parallel downloads (default: 1; >1 disables the live progress bar)")
    engine.add_argument("--retries", type=int, default=10, metavar="N",
                        help="network retries per item (default: 10)")
    engine.add_argument("--format", default=None, metavar="SELECTOR",
                        help="raw yt-dlp format selector — overrides -q/--quality")
    engine.add_argument("--cookies", default=None, metavar="FILE",
                        help="Netscape-format cookies.txt (for age-restricted/member videos)")
    engine.add_argument("-v", "--verbose", action="store_true",
                        help="show yt-dlp debug output")
    engine.add_argument("--update-ytdlp", action="store_true",
                        help="update yt-dlp (via pip) to the latest version and exit")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args(argv)

    if not args.targets:
        parser.print_help()
        raise SystemExit(2)
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    # --audio-format implies audio-only
    if args.audio_format and args.quality != "audio":
        args.quality = "audio"
    for opt in ("min_length", "max_length"):
        try:
            setattr(args, opt, parse_len(getattr(args, opt)) if getattr(args, opt) else None)
        except ValueError:
            parser.error(f"--{opt.replace('_', '-')} must be like '90', '2:30' or '1:02:00'")
    return args


def parse_len(text) -> int | None:
    """'90' -> 90s, '2:30' -> 150s, '1:02:00' -> 3720s."""
    if text is None:
        return None
    text = str(text).strip().lower()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if not all(p.isdigit() for p in parts) or len(parts) > 3:
            raise ValueError(text)
        secs = 0
        for p in parts:
            secs = secs * 60 + int(p)
        return secs
    if not text.isdigit():
        raise ValueError(text)
    return int(text)


def collect_urls(targets, dedupe: bool) -> list:
    urls, seen, dropped = [], set(), 0
    for target in targets:
        if os.path.isfile(target):
            with open(target, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.readlines()
        else:
            # also accept comma-separated URLs on the command line
            lines = target.split(",")
        for raw in lines:
            u = raw.strip()
            if not u or u.startswith("#"):
                continue
            key = u.lower()
            if dedupe and key in seen:
                dropped += 1
                continue
            seen.add(key)
            urls.append(u)
    if dropped:
        log(f"· skipped {dropped} duplicate URL(s)")
    return urls


# ------------------------------------------------------------ yt-dlp opts ----
def find_ffmpeg() -> str | None:
    """Locate a bundled or system-wide ffmpeg; returns the containing folder."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "ffmpeg", "bin"),
        os.path.join(here, "ffmpeg"),
    ]
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "ffmpeg.exe")) or \
           os.path.isfile(os.path.join(cand, "ffmpeg")):
            return cand
    found = shutil.which("ffmpeg")
    return os.path.dirname(found) if found else None


def format_for(args, has_ffmpeg: bool) -> str:
    """Pick a yt-dlp format selector that never *requires* merging when
    FFmpeg is unavailable (fallbacks below always end on a muxed single file)."""
    selector = args.format
    if selector:
        return selector
    q = args.quality
    if q == "best":
        return "bestvideo*+bestaudio/best" if has_ffmpeg else "best"
    if q == "audio":
        return "bestaudio/best" if has_ffmpeg else "bestaudio/best/best"
    height = int(q)
    if has_ffmpeg:
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    return f"best[height<={height}]/best"


def build_ydl_opts(args, ffmpeg_dir, archive, hook):
    dest = args.dest
    audio_only = args.quality == "audio"
    has_ffmpeg = ffmpeg_dir is not None

    postprocessors = []
    if not args.no_meta and has_ffmpeg:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if audio_only:
        if has_ffmpeg:
            codec = args.audio_format or "mp3"
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                # mp3 → fixed 320 kbps CBR; other codecs keep 'best' handling
                "preferredquality": "320" if codec == "mp3" else "0",
            })
    if not args.no_thumb and has_ffmpeg:
        postprocessors.append({"key": "EmbedThumbnail"})

    opts = {
        "format": format_for(args, has_ffmpeg),
        "outtmpl": os.path.join("%(title)s [%(id)s].%(ext)s"),
        "paths": {"home": dest},
        "quiet": not args.verbose,
        "verbose": args.verbose,
        "no_warnings": not args.verbose,
        "noprogress": True,               # we render our own progress
        "progress_hooks": [hook],
        "retries": args.retries,
        "fragment_retries": args.retries,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "ignoreerrors": False,
        "concurrent_fragment_downloads": 4,
        "noplaylist": args.no_playlist,
        "writethumbnail": (not args.no_thumb) and has_ffmpeg,
        "postprocessors": postprocessors,
    }
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir
    if archive and not args.redo:
        opts["download_archive"] = archive
    if args.playlist_limit and args.playlist_limit > 0:
        opts["playlistend"] = args.playlist_limit
    if args.subs:
        opts["writesubtitles"] = True
        opts["subtitleslangs"] = [s.strip() for s in args.subs_langs.split(",") if s.strip()]
    if args.cookies:
        opts.update(cookieopts(args))
    return opts


# --------------------------------------------------------------- progress ----
def _item_title(d) -> str:
    info = d.get("info_dict") or {}
    title = info.get("title")
    if not title:
        fname = d.get("filename") or "?"
        title = os.path.splitext(os.path.basename(fname))[0]
    return str(title)[:60]


def make_hook(prefix: str, parallel: bool):
    """progress hook — inline bar (CLI) or sparse Activity lines (GUI);
    the GUI parses these lines into the big progress bar."""
    state = {"pct": -100.0}

    def hook(d):
        if _CANCEL_LATCH.is_set():
            # Stop works mid-download: hooks run tight in the transfer loop
            raise RunCancelled()
        status = d.get("status")

        if status == "downloading" and _LOG is not None:
            # GUI mode: sparse >=5%-step lines so the log stays readable
            title = _item_title(d)
            got = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total > 0:
                pct = got * 100.0 / total
            else:
                pct = None
            if pct is None:
                if state["pct"] < 0:
                    state["pct"] = 0.0
                    log(f"{prefix} … {human_size(got)}"
                        f"{'' if parallel else ' (size unknown)'}")
                return
            if pct < state["pct"] + 5.0 and pct < 99.0:
                return
            state["pct"] = pct
            speed, eta = d.get("speed"), d.get("eta")
            body = (f"{pct:5.1f}%  {human_size(got)}"
                    + (f"/{human_size(total)}" if total else ""))
            if speed:
                body += f"  {human_size(speed)}/s"
            if eta:
                body += f"  ETA {human_time(eta)}"
            log(f"{prefix} … {body}")
            return

        if status == "downloading":
            title = _item_title(d)
            got = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed, eta = d.get("speed"), d.get("eta")
            pct = (got * 100.0 / total) if total > 0 else None
            w = term_width()
            if pct is not None:
                filled = min(24, int(pct / 100.0 * 24))
                bar = "#" * filled + "-" * (24 - filled)
                line = f"{prefix} {title:<48.48} [{bar}] {pct:5.1f}% {human_size(got)}" \
                       + (f"/{human_size(total)}" if total else "")
            else:
                line = f"{prefix} {title:<48.48} [--------]  ??% {human_size(got)}"
            if speed:
                line += f" {human_size(speed)}/s"
            if eta:
                line += f" ETA {human_time(eta)}"
            with PRINT_LOCK:
                try:
                    print("\r" + line[:w] + " " * max(0, w - (len(line) + 2)),
                          end="", flush=True)
                except Exception:
                    pass
        elif status == "finished":
            if _LOG is not None:
                log(f"{prefix} … 100.0% — converting / merging…")
            elif not parallel:
                title = _item_title(d)
                with PRINT_LOCK:
                    print(f"\r{prefix} {title:<48.48} [########################] 100.0%"
                          f" — merging / processing…", flush=True)
    return hook


_RETRYABLE_RE = re.compile(
    r"page needs to be reloaded"
    r"|not a bot"
    r"|429|too many requests"
    r"|403|forbidden"
    r"|sign in to confirm"
    r"|try again later"
    r"|requested format is not available",
    re.I)

# Fallback ladder of player clients that bypass bot-gated webpage state
# (no PO-token path used by community fallbacks; run as sequential passes).
# Cookieless entries come FIRST: exported web-session cookies are the most
# common cause of "The page needs to be reloaded" on watch pages, and public
# videos never need them. A cookied try stays last (age-gated videos).
_PLAYER_FALLBACKS = [
    ({"youtube": {"player_client": ["android", "web_safari"]}}, True),
    ({"youtube": {"player_client": ["tv_simply"]}}, True),
    ({"youtube": {"player_client": ["android", "web_safari"]}}, False),
]

_PLAYER_NAMES = {
    1: "android + web_safari (no cookies)",
    2: "tv_simply (no cookies)",
    3: "android + web_safari (logged in)",
}


def _all_passes() -> list:
    """Every attempt in ladder order — index 0 = 'as configured'."""
    return [(None, False)] + list(_PLAYER_FALLBACKS)


def _pass_signature(pos: int) -> str:
    """Stable string id for a pass (survives ladder reorderings)."""
    clients, drop = _all_passes()[pos]
    if clients is None:
        return "default"
    return ("+".join(clients["youtube"]["player_client"])
            + ("|nocookie" if drop else ""))


def _signature_index(sig: str):
    if not sig:
        return None
    for i in range(len(_all_passes())):
        if _pass_signature(i) == sig:
            return i
    return None

# Adaptive memory: on a poisoned session the FIRST item can burn the whole
# ladder before something works; remember the winning pass so the remaining
# items — and the next app session — start there directly.
_ADAPTIVE_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "MistusBatchYTDownloader", "adaptive.json")
_ADAPTIVE_MEMO: dict = {}


def _adaptive_load(cookiefile: str):
    """Remembered winning pass signature for this cookie file (str|None)."""
    key = cookiefile or ""
    if key not in _ADAPTIVE_MEMO:
        sig = None
        try:
            with open(_ADAPTIVE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("cookiefile", "") == key:
                s = str(data.get("win", ""))
                if _signature_index(s) is not None:
                    sig = s
        except Exception:
            sig = None
        _ADAPTIVE_MEMO[key] = sig
    return _ADAPTIVE_MEMO[key]


def _adaptive_save(cookiefile: str, sig: str | None) -> None:
    _ADAPTIVE_MEMO[cookiefile or ""] = sig
    try:
        os.makedirs(os.path.dirname(_ADAPTIVE_PATH), exist_ok=True)
        with open(_ADAPTIVE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"cookiefile": cookiefile or "", "win": sig}, fh)
    except Exception:
        pass


def _with_player_fallbacks(base_opts: dict, prefix: str, run):
    """Run `run(ydl)` across player-client passes when YouTube hard-blocks.

    Order: the previously-learned winning pass (if any), then the configured
    pass, then the client ladder (cookieless entries first). Fresh cache
    between passes. Raises the last error when every pass fails;
    RunCancelled / KeyboardInterrupt pass through untouched."""
    passes = _all_passes()
    ckey = _session_key(base_opts)
    win = _signature_index(_adaptive_load(ckey))
    if win == 0:
        win = None
    order = ([win] if win is not None else []) + \
            [i for i in range(len(passes)) if i != win]
    for pos in order:
        _check_cancel()
        opts = base_opts
        clients, drop_cookies = passes[pos]
        if clients is not None:
            opts = dict(base_opts)
            opts["extractor_args"] = clients
            if drop_cookies:
                opts.pop("cookiefile", None)
                opts.pop("cookiesfrombrowser", None)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = run(ydl)
            if pos != 0 and _ADAPTIVE_MEMO.get(ckey) != _pass_signature(pos):
                _adaptive_save(ckey, _pass_signature(pos))
                log(f"{prefix} · learned: {_PLAYER_NAMES.get(pos, _pass_signature(pos))}"
                    " works in this session — trying it first from now on")
            return result
        except KeyboardInterrupt:
            raise
        except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as exc:
            msg = str(exc).replace("\n", " ")
            if msg.startswith("ERROR: "):
                msg = msg[len("ERROR: "):]
            remaining = order[order.index(pos) + 1:]
            if remaining and _RETRYABLE_RE.search(msg):
                _close_ytdlp_cache()
                log(f"{prefix} · hard block ({msg[:120]}) — retrying with an "
                    "alternate player / fresh cache…")
                continue
            raise


def _close_ytdlp_cache():
    """Drop yt-dlp's on-disk cache (stale webpage/nsig state)."""
    try:
        probe = yt_dlp.YoutubeDL({"quiet": True})
        cdir = getattr(getattr(probe, "cache", None), "cache_dir", None)
    except Exception:
        cdir = None
    if cdir and os.path.isdir(cdir):
        shutil.rmtree(cdir, ignore_errors=True)


_BROWSER_NAMES = ("firefox", "chrome", "chromium", "edge", "brave",
                  "opera", "safari", "vivaldi", "whale")

_CHROMIUM_BROWSERS = ("chrome", "chromium", "edge", "brave",
                      "opera", "vivaldi", "whale")


def _parse_browser_cookie(value):
    """'firefox' / 'chrome:Profile 2' / 'chrome:Work' / 'chrome:2'
    -> (browser, profile-or-None). None when the value is not a browser."""
    v = (value or "").strip()
    name, _, prof = v.partition(":")
    name = name.strip().lower()
    if name not in _BROWSER_NAMES:
        return None
    prof = prof.strip() or None
    if prof and name in _CHROMIUM_BROWSERS:
        prof = _resolve_chromium_profile(name, prof)
    return name, prof


def _resolve_chromium_profile(name: str, prof: str) -> str:
    """Match a stand-in profile against the browser's real folders.
    Accepts case-insensitive folder names ('profile 2'), DISPLAY names
    chosen in Chrome ('Work') and 1-based index numbers ('2')."""
    try:
        from yt_dlp.cookies import _get_chromium_based_browser_settings
        root = _get_chromium_based_browser_settings(name)["browser_dir"]
        with open(os.path.join(root, "Local State"),
                  "r", encoding="utf-8", errors="replace") as fh:
            info = json.load(fh).get("profile", {}).get("info_cache") or {}
    except Exception:
        return prof
    if not info:
        return prof
    folders = sorted(info.keys())
    if prof.lower() in (f.lower() for f in folders):
        return next(f for f in folders if f.lower() == prof.lower())
    for folder, meta in info.items():                 # display name match
        if str(meta.get("name", "")).strip().lower() == prof.lower():
            return folder
    if prof.isdigit():                                # '2' → 2nd profile
        if 1 <= int(prof) <= len(folders):
            return folders[int(prof) - 1]
    return prof


def _is_browser_cookie(value) -> bool:
    return _parse_browser_cookie(value) is not None


def cookieopts(args) -> dict:
    """Cookie options for the ydl opts dict. Accepts a cookies.txt PATH or
    a live browser NAME (firefox / chrome / chrome:Profile 2 / …). Live
    browser cookies are the reliable long-run choice: they never expire
    between runs (a stale export file is the #1 long-run error source)."""
    c = getattr(args, "cookies", None)
    if not c:
        return {}
    parsed = _parse_browser_cookie(c)
    if parsed:
        return {"cookiesfrombrowser": parsed}
    return {"cookiefile": c}


def _probe_browser_cookies(args) -> bool:
    """Pre-flight load of live-browser cookies, once per run.

    Returns True when cookies are usable (or the input is not a browser).
    On failure it logs the reason plus the concrete fix and switches the
    whole run to cookieless — far better than a raw traceback mid-scan.
    The main real-world failure is Chrome 127+ 'app-bound encryption'
    (yt-dlp issue #10927): Google encrypts Chrome's cookie DB so that only
    Chrome itself can decrypt it; no external tool can read it anymore."""
    parsed = _parse_browser_cookie(getattr(args, "cookies", None))
    if not parsed:
        return True
    name, prof = parsed
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(name, prof)
        log(f"· cookies: live browser session via {name}"
            + (f" (profile '{prof}')" if prof else " (default profile)")
            + f" — {len(jar)} cookies, always fresh")
        return True
    except Exception as exc:
        msg = str(exc).replace("\n", " ")
        log(f"· cookies: browser '{name}' could not be read — {msg[:140]}")
        if "dpapi" in msg.lower() or "decrypt" in msg.lower():
            log("· cookies: this is Chrome 127+ 'app-bound encryption' — Google")
            log("  blocks ALL external tools from decrypting (yt-dlp issue #10927).")
            log("  Working fixes:  1) type  firefox  in the cookies field (Firefox")
            log("  has no encryption wall), or  2) export cookies.txt with the")
            log("  'Get cookies.txt LOCALLY' Chrome extension and select that file.")
        else:
            log("· cookies: fix the browser session, or use a cookies.txt file instead.")
        log("· cookies: continuing WITHOUT cookies — public channels work fine")
        log("  (the player-fallback ladder is cookieless-first by design).")
        args.cookies = None
        return False


def _session_key(opts: dict) -> str:
    """Marker used for the adaptive player memory (cookie-file or browser)."""
    cb = opts.get("cookiesfrombrowser")
    if cb:
        return ":".join(str(x) for x in cb if x is not None)
    return str(opts.get("cookiefile") or "")


def _delay_jitter(delay: float) -> float:
    """scan delay with ±25% jitter — fixed intervals look robotic."""
    if delay and delay > 0:
        return max(2.0, delay * (0.75 + 0.5 * random.random()))
    return 0.0


def download_one(index: int, total: int, url: str, args, ffmpeg_dir, archive) -> tuple:
    """Download a single URL. Returns (ok: bool, error: str|None)."""
    _check_cancel()
    prefix = f"[{index}/{total}]"
    hook = make_hook(prefix, parallel=(args.jobs > 1))
    opts = build_ydl_opts(args, ffmpeg_dir, archive, hook)
    log(f"{prefix} ▸ {url}")

    def _run(ydl):
        if getattr(args, "quality", "") == "audio":
            # best-audio system: tags on every audio download
            try:
                ydl.add_post_processor(
                    _SetMusicMetaPP(ydl,
                                    artist=getattr(args, "artist", None),
                                    title=getattr(args, "song_title", None)),
                    when="pre_process")
            except Exception:
                pass
        ydl.download([url])

    try:
        _with_player_fallbacks(opts, prefix, _run)
        log(f"{prefix} ✓ done")
        return True, None
    except KeyboardInterrupt:
        log(f"{prefix} ! interrupted")
        raise
    except RunCancelled:
        log(f"{prefix} ■ stopped by user")
        raise
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).replace("\n", " ")
        if msg.startswith("ERROR: "):
            msg = msg[len("ERROR: "):]
        log(f"{prefix} ✗ FAILED: {msg[:200]}")
        if _RETRYABLE_RE.search(msg):
            msg += ("  [hint: YouTube is throttling this session — re-export "
                    "cookies.txt, raise --scan-delay, or press ⬆ Update "
                    "yt-dlp; then retry]")
        return False, msg
    except Exception as exc:  # unexpected
        log(f"{prefix} ✗ FAILED: {exc}")
        return False, str(exc)


# ------------------------------------------------------------ channel scan ----
def looks_like_channel(url: str) -> bool:
    """Heuristic: channel-ish YouTube URLs default to scan mode."""
    try:
        path = urlparse(url).path.rstrip("/").lower()
    except ValueError:
        return False
    first = next((p for p in path.split("/") if p), "")
    return first.startswith("@") or first in ("channel", "c", "user", "videos", "shorts")


def _channel_tab_urls(url: str, include_shorts: bool) -> list:
    path = urlparse(url).path.rstrip("/").lower()
    if path.endswith("/shorts"):
        return [url]
    if path.endswith("/videos"):
        tabs = [url]
        if include_shorts:
            tabs.append(url[: -len("/videos")] + "/shorts")
        return tabs
    base = url.rstrip("/")
    tabs = [f"{base}/videos"]
    if include_shorts:
        tabs.append(f"{base}/shorts")
    return tabs


def scan_channel(url: str, args) -> tuple[str, list]:
    """Flat-extract a channel's videos (+shorts). Returns (channel_name, videos)."""
    log(f"· scanning channel: {url}")
    videos, seen = [], set()
    chan_name = None
    scan_opts = {
        "quiet": not args.verbose,
        "verbose": args.verbose,
        "no_warnings": not args.verbose,
        "extract_flat": True,
        "socket_timeout": 30,
        "extractor_retries": 3,
        "ignoreerrors": True,          # skip dead members instead of dying
        "logger": None,
    }
    if args.cookies:
        scan_opts.update(cookieopts(args))
    if args.playlist_limit and args.playlist_limit > 0:
        scan_opts["playlistend"] = args.playlist_limit
    for tab in _channel_tab_urls(url, include_shorts=args.shorts):
        is_short_tab = tab.rstrip("/").lower().endswith("/shorts")
        log(f"· scan tab: {tab}")
        with yt_dlp.YoutubeDL(scan_opts) as ydl:
            info = ydl.extract_info(tab, download=False)
        if not info:
            continue
        chan_name = chan_name or (info.get("channel") or info.get("uploader")
                                  or info.get("title") or "channel")
        for e in (info.get("entries") or []):
            if not e or not e.get("id"):
                continue
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            videos.append({
                "id": e.get("id"),
                "title": e.get("title") or e.get("id"),
                "url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id')}",
                "duration": e.get("duration"),
                "short": bool(is_short_tab or e.get("shorts_only") or
                              (e.get("duration") or 0) and (e.get("duration") or 0) <= 0),
            })
    return (chan_name or "channel"), videos


def _length_ok(duration, v_min, v_max) -> bool:
    """Bounds: 0 / None both mean 'no bound'. UNKNOWN durations are kept —
    a channel listing that misses durations must never wipe a batch."""
    has_min = bool(v_min)
    has_max = bool(v_max)
    if not has_min and not has_max:
        return True
    if duration is None:
        log("  note: duration unknown on a filtered channel — item kept, "
            "filter ignored for it")
        return True
    if has_min and duration < v_min:
        return False
    if has_max and duration > v_max:
        return False
    return True


def _fmt_dur(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "?"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clean_title(title: str) -> str:
    t = yt_dlp.utils.sanitize_filename(str(title), restricted=True)
    t = re.sub(r"\s+", "_", t.strip()) or "untitled"
    return t[:100]


def _scan_prefixes(dirs: dict) -> tuple[dict, int]:
    """Inventory numbered files across the output subfolders.

    Returns (title_key -> existing number, highest number seen)."""
    known: dict[str, int] = {}
    highest = 0
    for d in dirs.values():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            m = re.match(r"^(\d+)_(.*)$", name)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            highest = max(highest, n)
            key = os.path.splitext(m.group(2))[0]
            known.setdefault(key, n)
    return known, highest


_GAP_SEEN: set[int] = set()


def _audio_numbers(audio_dir: str) -> set[int]:
    """Prefix numbers that have a real (non-partial) audio file on disk."""
    out: set[int] = set()
    try:
        names = os.listdir(audio_dir)
    except OSError:
        return out
    for name in names:
        if ".part" in name or name.endswith(".ytdl"):
            continue
        m = re.match(r"^(\d+)_", name)
        if m:
            try:
                out.add(int(m.group(1)))
            except ValueError:
                pass
    return out


def _load_manifest(path: str) -> dict:
    """_numbering.json contents ({\"5\": {title, url}, …}), {} if absent."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sync_manifest(man, man_path, no: int, vid) -> None:
    """Record slot number -> title + url (atomic-ish write) so a later
    deletion of ALL files for that slot can still be re-filled precisely."""
    if man is None or man_path is None or no is None:
        return
    man[str(no)] = {"title": vid.get("title") or "",
                    "url": vid.get("url") or ""}
    try:
        tmp = man_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(man, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, man_path)
    except OSError:
        pass


def _sibling_title(dirs: dict, n: int):
    """Recover an item's title from its Thumbnail / Text File files
    (they share the sanitized stem with the deleted audio file)."""
    for d in (dirs["thumb"], dirs["info"]):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if name.endswith(".part"):
                continue
            stem, ext = os.path.splitext(name)
            if not ext and d is dirs["thumb"]:
                continue
            m = re.match(rf"^{n}_(.+)$", stem)
            if m:
                return m.group(1)
    return None


def _plan_repairs(dirs: dict, highest: int, known: dict,
                  manifest: dict) -> dict:
    """Find audio slots 1..highest with no audio file and build refill
    candidates for each slot: (missing, by_url, by_title). The numbered
    manifest is the primary source, Thumbnail/Text File stems the fallback.
    Items already saved under another number are never duplicated."""
    have = _audio_numbers(dirs["audio"])
    missing = [n for n in range(1, highest + 1) if n not in have]
    by_url: dict[str, int] = {}
    by_title: dict[str, int] = {}
    for n in missing:
        rec = manifest.get(str(n))
        if rec:
            tkey = _clean_title(rec.get("title") or "")
            # refill only when the item is not already saved elsewhere
            if rec.get("url") and known.get(tkey, n) == n:
                by_url[rec["url"]] = n
                continue
        sib = _sibling_title(dirs, n)
        if sib is not None and known.get(sib, n) == n:
            by_title[sib] = n
    return {"have": have, "missing": missing,
            "by_url": by_url, "by_title": by_title}


def _music_info(info) -> str:
    artists = info.get("artists") or info.get("artist") or []
    if isinstance(artists, list):
        artists = ", ".join(artists)
    composers = info.get("composer") or []
    if isinstance(composers, list):
        composers = ", ".join(composers)
    pairs = [
        ("Track", info.get("track")),
        ("Artist", artists or info.get("creator") or info.get("uploader")),
        ("Album", info.get("album")),
        ("Composer", composers),
        ("Track number", info.get("track_number")),
        ("Release date", info.get("release_date")),
    ]
    rows = [f"    {k}: {v}" for k, v in pairs if v]
    return "\n".join(rows) if rows else "    (none)"


def vtt_to_text(path: str) -> str:
    out = []
    tag_re = re.compile(r"<[^>]+>")
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or "-->" in line or line.isdigit():
                continue
            if line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:", "STYLE", "REGION")):
                continue
            line = tag_re.sub("", line).strip()
            # drop consecutive duplicate lines (rolling captions)
            if line and (not out or line != out[-1]):
                out.append(line)
    return "\n".join(out)


def _match_caption_tracks(info, langs: list):
    """(lang, formats) of the first requested language available, or None."""
    for key in ("automatic_captions", "subtitles"):
        data = info.get(key) or {}
        if not data:
            continue
        for lang in langs:
            if lang in data:
                return lang, data[lang]
            if lang.endswith(".*"):
                base = lang[:-2]
                for k in data:
                    if k == base or k.startswith(base + "-"):
                        if data.get(k):
                            return k, data[k]
    return None


def _fetch_transcript_from_info(info, langs: list, workdir: str, args) -> tuple:
    """Fetch a caption VTT straight from the track URL the metadata
    extraction ALREADY returned. The old path hit the watch page a second
    time per video, which is what kept tripping YouTube's subtitle
    endpoint (HTTP 429) and burned ladder retries on every item."""
    found = _match_caption_tracks(info, langs)
    if not found:
        return "", ""
    track_lang, fmts = found
    pick = None
    for f in fmts or []:
        if f.get("ext") == "vtt":
            pick = f
            break
    if pick is None and fmts:
        pick = fmts[0]
    url = (pick or {}).get("url")
    if not url:
        return "", ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        if args.verbose:
            log(f"  note: transcript skipped ({str(exc)[:80]})")
        return "", ""
    path = os.path.join(workdir, f"cap.{track_lang}.vtt")
    with open(path, "wb") as fh:
        fh.write(raw)
    return track_lang, vtt_to_text(path)


def _fetch_transcript(url: str, langs: list, workdir: str, args) -> tuple[str, str]:
    """Download captions with a skip-download run; returns (lang, transcript)."""
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": langs,
        "subtitlesformat": "vtt/best",
        "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
        "quiet": not args.verbose,
        "verbose": args.verbose,
        "no_warnings": not args.verbose,
        "noprogress": True,
        "socket_timeout": 30,
        "extractor_retries": 3,
    }
    if args.cookies:
        opts.update(cookieopts(args))
    try:
        _with_player_fallbacks(opts, "  ", lambda ydl: ydl.download([url]))
    except Exception as exc:
        if args.verbose:
            log(f"  note: caption fetch hiccup: {exc}")
    for name in sorted(os.listdir(workdir)):
        if name.endswith(".vtt"):
            return (os.path.splitext(name)[0].rsplit(".", 1)[-1], vtt_to_text(os.path.join(workdir, name)))
    return ("", "")


def write_info_txt(path: str, vid, info, transcript: str, t_lang: str) -> None:
    tags = info.get("tags") or []
    lines = [
        f"Video URL: {vid.get('url') or 'https://www.youtube.com/watch?v=' + str(vid.get('id'))}",
        f"Video Title: {info.get('title') or vid.get('title')}",
        f"Channel: {info.get('channel') or info.get('uploader') or ''}",
        f"Upload date: {info.get('upload_date') or ''}",
        f"Duration: {_fmt_dur(info.get('duration'))}",
        f"Views: {info.get('view_count') or ''}",
        "",
        "Description:",
        (info.get("description") or "(no description)").strip(),
        "",
        f"Tags: {', '.join(tags) if tags else '(none)'}",
        "Music information:",
        _music_info(info),
        "",
        f"Transcription{(f' [{t_lang}]' if t_lang else '')}:",
        transcript or "(no captions available)",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _clean_thumb_strays(thumb_dir: str, prefix: str, keep_ext: str) -> None:
    """Remove intermediate thumbnail files once the final one exists."""
    for name in os.listdir(thumb_dir):
        if not name.startswith(prefix + "."):
            continue
        base, ext = os.path.splitext(name)
        if ext.lower() in (".webp", ".jpg", ".jpeg", ".avif") and ext.lower() != keep_ext.lower():
            try:
                os.remove(os.path.join(thumb_dir, name))
            except OSError:
                pass


def _ffmpeg_bin(ffmpeg_dir) -> str | None:
    """Return an ffmpeg executable path, or None."""
    if ffmpeg_dir:
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(ffmpeg_dir, name)
            if os.path.isfile(p):
                return p
    return shutil.which("ffmpeg")


def _thumb_exists(thumb_dir: str, stem: str) -> bool:
    return any(os.path.isfile(os.path.join(thumb_dir, stem + ext))
               for ext in (".png", ".jpg", ".jpeg", ".webp"))


def _fetch_thumbnail(info, stem: str, thumb_dir: str, ffmpeg_dir, args) -> str | None:
    """Download the video thumbnail and convert it to PNG (when ffmpeg exists)."""
    url = info.get("thumbnail") or ""
    if not url:
        return None
    data = b""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; YT-Batch-Downloader-Mistu)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as exc:
        log(f"  note: thumbnail fetch failed: {exc}")
        return None
    ext = ".png" if data.startswith(b"\x89PNG") else \
          ".webp" if data.startswith(b"RIFF") else ".jpg"
    src = os.path.join(thumb_dir, stem + ext)
    try:
        with open(src, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        log(f"  note: thumbnail save failed: {exc}")
        return None
    if ext == ".png":
        return f"{stem}.png"
    ffmpeg = _ffmpeg_bin(ffmpeg_dir)
    if not ffmpeg:
        return os.path.basename(src)          # keep original format (no ffmpeg)
    dst = os.path.join(thumb_dir, stem + ".png")
    try:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-hide_banner",
                        "-i", src, "-update", "1", dst],
                       check=True, timeout=60)
    except Exception as exc:
        log(f"  note: thumbnail conversion to PNG failed ({exc}) — keeping {ext}")
        return os.path.basename(src)
    try:
        os.remove(src)
    except OSError:
        pass
    return f"{stem}.png"


def process_scan_item(index: int, total: int, vid, args, ffmpeg_dir,
                      dirs: dict, item_no: int | None = None,
                      manifest=None, manifest_path: str | None = None) -> tuple:
    """Download audio + thumbnail + write info txt for one scanned video.
    item_no is the file-number prefix (continues across sessions)."""
    _check_cancel()
    prefix = f"[{index}/{total}]"
    safe = _clean_title(vid["title"])
    stem = f"{item_no if item_no is not None else index}_{safe}"
    audio_dir, thumb_dir, info_dir = dirs["audio"], dirs["thumb"], dirs["info"]
    audio_dst = os.path.join(audio_dir, stem + ".%(ext)s")

    # migrate: remove stray thumbnail files that old versions wrote into audio/
    for _ext in (".png", ".jpg", ".jpeg", ".webp"):
        _stray = os.path.join(audio_dir, stem + _ext)
        if os.path.isfile(_stray):
            try:
                os.remove(_stray)
            except OSError:
                pass

    # ---- partial downloads are NOT done audio (a killed .part file must
    # re-download next run, not be skipped as "already saved") -----------
    audio_done = any(f.startswith(stem + ".")
                     and ".part" not in f and not f.endswith(".ytdl")
                     for f in os.listdir(audio_dir))
    info_done = os.path.isfile(os.path.join(info_dir, stem + ".txt"))
    thumb_done = _thumb_exists(thumb_dir, stem)

    # ---- instant resume: fully saved items cost zero network calls ------
    log(f"{prefix} ▸ {vid['title']} ({_fmt_dur(vid.get('duration'))})")
    if audio_done and info_done and thumb_done:
        log(f"{prefix} ✓ skipped (already saved)")
        _sync_manifest(manifest, manifest_path, item_no, vid)
        return True, None

    # ---- metadata ----
    meta_opts = {
        "quiet": not args.verbose,
        "verbose": args.verbose,
        "no_warnings": not args.verbose,
        "socket_timeout": 30,
        "extractor_retries": 3,
    }
    if args.cookies:
        meta_opts.update(cookieopts(args))
    # cookie state can poison the watch page ("page needs to be reloaded")
    # — reach for the same player-client ladder the downloads use
    info = _with_player_fallbacks(
        meta_opts, prefix,
        lambda ydl: ydl.extract_info(vid["url"], download=False))
    if not info:
        return False, "metadata extraction failed"

    # ---- transcript (only if the info txt is missing) ----
    if info_done:
        t_lang, transcript = "", ""
    else:
        with tempfile.TemporaryDirectory(prefix="mistu-cap-") as capdir:
            t_lang, transcript = _fetch_transcript_from_info(
                info, ["en-orig", "en.*"], capdir, args)

    # ---- audio (mp3/m4a/... via bundled ffmpeg) ----
    if not audio_done:
        audio_format = args.audio_format or "mp3"
        post = []
        if ffmpeg_dir:
            post.append({"key": "FFmpegMetadata", "add_metadata": True})
            post.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                # mp3 → fixed 320 kbps CBR; other codecs keep 'best' handling
                "preferredquality": "320" if audio_format == "mp3" else "0",
            })
        opts = {
            "format": "bestaudio/best" if ffmpeg_dir else "bestaudio/best/best",
            "outtmpl": audio_dst,
            "writethumbnail": False,
            "quiet": not args.verbose,
            "verbose": args.verbose,
            "no_warnings": not args.verbose,
            "noprogress": True,
            "progress_hooks": [make_hook(prefix, parallel=False)],
            "retries": args.retries,
            "socket_timeout": 30,
            "extractor_retries": 3,
            "postprocessors": post,
        }
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir

        def _run_audio(ydl):
            artist = getattr(args, "artist", None)
            song_title = getattr(args, "song_title", None)
            try:
                ydl.add_post_processor(
                    _SetMusicMetaPP(ydl, artist=artist,
                                    title=song_title),
                    when="pre_process")
            except Exception:
                pass
            ydl.download([vid["url"]])

        _with_player_fallbacks(opts, prefix, _run_audio)
        _bitrate = " @ 320 kbps" if audio_format == "mp3" else ""
        log(f"{prefix} ✓ audio saved: Audio/{stem}.{audio_format}{_bitrate}")

    # ---- thumbnail (separate folder, converted to PNG when ffmpeg exists) ----
    if not thumb_done:
        thumb_name = _fetch_thumbnail(info, stem, thumb_dir, ffmpeg_dir, args)
        if thumb_name:
            log(f"{prefix} ✓ thumbnail saved: Thumbnail/{thumb_name}")
        elif not args.verbose:
            log(f"{prefix} · thumbnail: none available")

    # ---- info txt ----
    if not info_done:
        write_info_txt(os.path.join(info_dir, stem + ".txt"), vid, info, transcript, t_lang)
        log(f"{prefix} ✓ info saved: Text File/{stem}.txt")
    _sync_manifest(manifest, manifest_path, item_no, vid)
    return True, None


def run_scan(url: str, args, ffmpeg_dir) -> tuple:
    """Full channel scan. Returns (ok_count, [(url, err), ...])."""
    chan_name, videos = scan_channel(url, args)
    longs = [v for v in videos if not v["short"]]
    shorts = [v for v in videos if v["short"]]
    log(f"· found {len(longs)} long video(s), {len(shorts)} short(s) — channel: {chan_name}")

    # length filter: shorts are filtered with the same bounds
    filtered = [v for v in videos if _length_ok(v.get("duration"), args.min_length, args.max_length)]
    dropped = len(videos) - len(filtered)
    if dropped:
        lo = _fmt_dur(args.min_length) if args.min_length else "any"
        hi = _fmt_dur(args.max_length) if args.max_length else "any"
        log(f"· length filter {lo} … {hi}: {len(filtered)} of {len(videos)} kept ({dropped} skipped)")
    if args.playlist_limit and args.playlist_limit > 0:
        filtered = filtered[: args.playlist_limit]

    if not filtered:
        return 0, []

    dest = os.path.abspath(args.dest)
    dirs = {
        "audio": os.path.join(dest, "Audio"),
        "thumb": os.path.join(dest, "Thumbnail"),
        "info": os.path.join(dest, "Text File"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    log(f"· output folder: {dest}")
    log(f"· subfolders: Audio / Thumbnail / Text File")

    # numbering: continue right after the numbers already on disk; a title
    # that exists reuses its old number (resume), new titles get fresh ones
    known, highest = _scan_prefixes(dirs)
    next_no = highest + 1
    if highest:
        log(f"· found files up to #{highest} — numbering continues from #{next_no}")

    # gap repair: deleted audio leaves a hole between numbers. A numbered
    # manifest (_numbering.json) and the Thumbnail/Text File stems let us
    # put the exact video back into its original slot.
    m_path = os.path.join(dest, "_numbering.json")
    manifest = _load_manifest(m_path)
    if not os.path.isfile(m_path):
        log("· numbering manifest: _numbering.json (records every item's "
            "slot, title and url so deleted files can be re-filled)")
    plan = _plan_repairs(dirs, highest, known, manifest)
    by_url, by_title = plan["by_url"], plan["by_title"]
    missing = plan["missing"]
    if missing:
        fresh = [n for n in missing if n not in _GAP_SEEN]
        _GAP_SEEN.update(missing)
        if fresh:
            log(f"· gap check: {len(missing)} audio slot(s) missing: "
                + ", ".join(f"#{n}" for n in fresh))
            for n in fresh:
                rec = manifest.get(str(n))
                sib = next((t for t, x in by_title.items() if x == n), None)
                if n in by_url.values() and rec:
                    log(f"  slot #{n} ⟳ will re-download "
                        f"({(rec.get('title') or '')[:64]})")
                elif sib:
                    log(f"  slot #{n} ⟳ will re-download ({sib[:64]})")
                else:
                    log(f"  slot #{n} ⚠ stays empty — all its files were "
                        "deleted, so the item cannot be identified")

    ok_n, fails = 0, []
    total = len(filtered)
    for i, vid in enumerate(filtered, 1):
        key = _clean_title(vid["title"])
        no = known.get(key)
        if no is None and vid["url"] in by_url:
            no = by_url.pop(vid["url"])
            log(f"[{i}/{total}] ⟳ re-filling deleted slot #{no}")
        if no is None and key in by_title:
            no = by_title.pop(key)
            log(f"[{i}/{total}] ⟳ re-filling deleted slot #{no}")
        if no is None:
            no = next_no
            next_no += 1
        if i > 1 and args.scan_delay and args.scan_delay > 0:
            # jittered latch sleep: pressing Stop cuts the delay instantly
            wait = _delay_jitter(args.scan_delay)
            if wait and _CANCEL_LATCH.wait(wait):
                _check_cancel()
        try:
            ok, err = process_scan_item(i, total, vid, args, ffmpeg_dir, dirs,
                                        item_no=no, manifest=manifest,
                                        manifest_path=m_path)
        except KeyboardInterrupt:
            log(f"\n! interrupted at {i}/{total} — done items are kept; re-run to resume")
            raise
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).replace("\n", " ")
            if msg.startswith("ERROR: "):
                msg = msg[len("ERROR: "):]
            if "not a bot" in msg or "429" in msg or "Too Many Requests" in msg:
                msg += ("  [hint: YouTube is rate-limiting/throttling this IP — raise "
                        "--scan-delay, wait some minutes, or pass --cookies cookies.txt]")
            log(f"[{i}/{total}] ✗ FAILED: {msg[:200]}")
            ok, err = False, msg
        if ok:
            ok_n += 1
        else:
            fails.append((vid["url"], err or "unknown error"))
    return ok_n, fails


def _is_channel_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower().rstrip("/")
    if host in ("youtube.com", "m.youtube.com"):
        for marker in ("/@", "/channel/", "/c/", "/user/"):
            if marker in path:
                return True
        if path.endswith(("/videos", "/shorts", "/streams")):
            return True
    if host.endswith("youtu.be"):
        return False
    return False


def _scan_flat(url: str, args) -> tuple[str, list]:
    """Flat-extract any URL (playlist / mix / single video). No download."""
    opts = {
        "quiet": not args.verbose,
        "verbose": args.verbose,
        "no_warnings": not args.verbose,
        "extract_flat": True,
        "socket_timeout": 30,
        "extractor_retries": 3,
        "ignoreerrors": True,
    }
    if getattr(args, "cookies", None):
        opts.update(cookieopts(args))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return url, []
    name = info.get("title") or info.get("channel") or url
    entries = info.get("entries")
    if entries is None:                      # a single direct video URL
        entries = [info]
    videos = []
    for e in entries or []:
        if not e or not (e.get("id") or e.get("url")):
            continue
        vid = e.get("id") or ""
        if e.get("ie_key") == "Youtube" and "/channel/" in (e.get("url") or ""):
            continue                          # nested channel sub-listing
        videos.append({
            "id": vid,
            "title": e.get("title") or vid,
            "url": e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "duration": e.get("duration"),
            "short": bool(e.get("shorts_only")),
        })
    return name, videos


def _emit_scan_report(tag: str, name: str, url: str, videos: list, args) -> None:
    """Log the detailed inventory for one scanned source."""
    longs = [v for v in videos if not v["short"]]
    shorts = [v for v in videos if v["short"]]
    secs = sum(v["duration"] for v in videos if isinstance(v["duration"], (int, float)))

    log(f"{tag} ────────────────────────────────────")
    log(f"{tag} :: source: {url}")
    log(f"{tag} :: name:   {name}")
    log(f"{tag} :: total items: {len(videos)}"
        f"   (videos: {len(longs)}, shorts: {len(shorts)}, runtime: {_fmt_dur(secs)})")

    v_min, v_max = args.min_length, args.max_length
    if v_min is not None or v_max is not None:
        lo = _fmt_dur(v_min) if v_min else "any"
        hi = _fmt_dur(v_max) if v_max else "any"
        matched = [v for v in videos
                   if _length_ok(v.get("duration"), v_min, v_max)]
        log(f"{tag} :: length filter {lo} – {hi} → {len(matched)} item(s) within range"
            f" ({len(videos) - len(matched)} outside range)")
        listing = matched
    else:
        listing = videos

    if getattr(args, "playlist_limit", 0) and args.playlist_limit > 0:
        listing = listing[: args.playlist_limit]

    if not listing:
        log(f"{tag} :: (no items to list — nothing matched the filter)")
        return

    log(f"{tag} :: listing {len(listing)} item(s):")
    for i, v in enumerate(listing, 1):
        blurb = ("[short] " if v["short"] else "") + str(v["title"])
        log(f"{tag}   {i:>4}. {_fmt_dur(v['duration']):>8}  {blurb}")


def scan_report_pipeline(args) -> int:
    """Dry-run: scan every target and log a detailed availability report.
    Returns 0 ok, 1 some sources failed, 130 stopped by user."""
    log("── SCAN REPORT ───────────────────────────────────────────────")
    try:
        fails = 0
        targets = [t for t in args.targets if t]
        for i, url in enumerate(targets, 1):
            _check_cancel()
            tag = f"[{i}/{len(targets)}]"
            try:
                if _is_channel_url(url):
                    name, videos = scan_channel(url, args)
                else:
                    name, videos = _scan_flat(url, args)
                if not videos:
                    log(f"{tag} :: (No entries or a private/blocked source — "
                        "cookies may be needed)")
                    fails += 1
                    continue
                _emit_scan_report(tag, name, url, videos, args)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as exc:
                msg = str(exc).replace("\n", " ")
                if msg.startswith("ERROR: "):
                    msg = msg[len("ERROR: "):]
                if "not a bot" in msg or "429" in msg or "Too Many Requests" in msg:
                    msg += ("  [hint: use a cookies.txt file — see README §Cookies]")
                log(f"{tag} ✗ scan failed: {msg[:260]}")
                fails += 1
        if fails:
            log(f"── report finished with {fails} failed source(s)")
            return 1
        log("── report finished ✔")
        return 0
    except RunCancelled:
        log("! scan report stopped by user")
        return 130


# ----------------------------------------------------------- update yt-dlp ---
def update_ytdlp() -> bool:
    """Update yt-dlp via pip using the current interpreter. Returns True on success."""
    log("· updating yt-dlp via pip (this may take a minute)…")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--break-system-packages", "yt-dlp"],
            capture_output=True, text=True,
        )
        if proc.stdout and proc.stdout.strip():
            for line in proc.stdout.strip().splitlines():
                log(line)
        if proc.stderr and proc.stderr.strip():
            for line in proc.stderr.strip().splitlines():
                log(line)
        if proc.returncode != 0:
            log(f"✗ yt-dlp update failed (exit code {proc.returncode})")
            return False
        try:
            import importlib
            importlib.reload(yt_dlp)
            log(f"✓ yt-dlp updated to {yt_dlp.version.__version__}")
        except Exception:
            log("✓ yt-dlp update completed")
        return True
    except Exception as exc:
        log(f"✗ yt-dlp update failed: {exc}")
        return False


# -------------------------------------------------------------------- main ---
BANNER = r"""
====================================================
  YT-Batch-Downloader-Mistu  v{ver}
  YouTube batch downloader •  engine: yt-dlp {ydlp}
====================================================
"""

_LOGIN_COOKIE_NAMES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
}


def _describe_cookies(path: str) -> tuple:
    """Inspect a Netscape cookies.txt. Returns (summary, problem|None).
    Counts are logged, never cookie values."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception as exc:
        return None, f"file unreadable ({exc})"
    total = yt_n = login_n = 0
    names = set()
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) < 7:
            continue
        total += 1
        dom = parts[0].lower()
        if "youtube" in dom or dom.endswith("google.com"):
            yt_n += 1
        name = parts[5]
        names.add(name)
        if name in _LOGIN_COOKIE_NAMES:
            login_n += 1
    if not total:
        return None, ("no cookies found — export the file from your browser "
                      "as Netscape format while logged in on youtube.com")
    summary = (f"{total} cookies (YouTube/Google: {yt_n}, "
               f"login session: {'yes' if login_n else 'NOT FOUND'})")
    if not yt_n:
        prob = ("no YouTube/Google cookies in this file — it was probably "
                "exported from another site; export it while ON youtube.com")
        return summary, prob
    if not login_n:
        prob = ("cookies present but no login session — export again while "
                "LOGGED IN on youtube.com (or just run without cookies)")
        return summary, prob
    return summary, None


def execute(args) -> int:
    """Run the full pipeline for parsed args. Usable from the CLI and the GUI.
    Returns 0 = all ok, 1 = some failures, 130 = stopped by user, 2 = bad input."""
    _GAP_SEEN.clear()          # each run reports its gaps fresh
    if getattr(args, "update_ytdlp", False):
        return 0 if update_ytdlp() else 1
    # --mode selects a download mode
    _mode = getattr(args, "mode", None)
    if _mode == "scan":
        args.scan = True
        args.regular = False
        args.music = False
    elif _mode == "regular":
        args.regular = True
        args.scan = False
        args.music = False
    elif _mode == "music":
        args.music = True

    # Music mode = the best-audio system:
    #   best available audio stream -> mp3 @ 320 kbps, cover art + tags
    if getattr(args, "music", False):
        args.quality = "audio"
        args.audio_format = "mp3"          # the best-audio system is mp3-only
        args.no_meta = False               # tags/cover art are always embedded
        args.no_thumb = False              # in the best-audio system
        args.regular = True
    ffmpeg_dir = find_ffmpeg()
    if ffmpeg_dir:
        log(f"· ffmpeg: {ffmpeg_dir}")
    else:
        log("· ffmpeg: NOT FOUND")
        if args.quality != "audio" or getattr(args, "music", False):
            log("error: ffmpeg is required for this mode "
                "(audio conversion / cover-art embedding).\n"
                "  - the installed app ships ffmpeg next to the program,\n"
                "  - or keep ffmpeg.exe/ffmpeg on PATH.")
            return 2

    try:
        urls = collect_urls(args.targets, dedupe=not args.keep_dupes)
    except OSError as exc:
        sys.stderr.write(f"error: cannot read input file: {exc}\n")
        return 2

    if not urls:
        log("error: no URLs given")
        return 2

    if args.no_archive or args.redo:
        archive = None
    elif args.archive:
        archive = args.archive
    else:
        archive = os.path.join(args.dest, "downloaded.txt")

    dest = os.path.abspath(args.dest)
    os.makedirs(dest, exist_ok=True)

    # cookie transparency + pre-flight: browser cookies are probed once so a
    # load failure (Chrome app-bound encryption, locked DB, …) degrades to a
    # clearly-explained cookieless run instead of crashing mid-scan.
    _probe_browser_cookies(args)
    if (getattr(args, "cookies", None)
            and not _is_browser_cookie(args.cookies)):
        cinfo, cprob = _describe_cookies(args.cookies)
        if cinfo:
            log(f"· cookies: {args.cookies}  ({cinfo})")
        if cprob:
            log(f"· cookies: {args.cookies}  ⚠ {cprob}")
    _jsnotes = [_x for _x in ("deno", "bun", "node")
                if shutil.which(_x)]
    if _jsnotes:
        log(f"· js runtime: {_jsnotes[0]} (ok)")
    else:
        log("· js runtime: none found — occasional format errors may occur; "
            "install once with  winget install OpenJS.NodeJS.LTS  to be safe")

    if getattr(args, "regular", False):
        scan_urls = []
    else:
        scan_urls = [u for u in urls if args.scan or looks_like_channel(u)]
    scan_set = set(scan_urls)
    batch_urls = [u for u in urls if u not in scan_set]

    if scan_urls:
        log(f"· channel URLs detected -> scan mode: {len(scan_urls)}")
        if batch_urls:
            log(f"· plain URLs (batch mode): {len(batch_urls)}")
    if batch_urls:
        pl = [u for u in batch_urls if "list=" in u.lower() or "/playlist" in u.lower()]
        if pl:
            log(f"· playlist URL(s) detected: {len(pl)} (downloads all items by default; "
                f"use --single/--no-playlist for one video)")
        log(f"· destination: {dest}")
        log(f"· items: {len(batch_urls)}   quality: {args.quality}   jobs: {args.jobs}")
        if archive and not args.redo:
            log(f"· archive: {archive}  (already-downloaded items will be skipped)")
    log("-" * 52)

    failures = []
    ok_count = 0
    try:
        if batch_urls:
            total_b = len(batch_urls)
            if args.jobs == 1:
                for i, url in enumerate(batch_urls, 1):
                    _check_cancel()
                    ok, err = download_one(i, total_b, url, args, ffmpeg_dir, archive)
                    if ok:
                        ok_count += 1
                    else:
                        failures.append((url, err or "unknown error"))
            else:
                with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                    futures = {
                        pool.submit(download_one, i, total_b, u, args, ffmpeg_dir, archive): u
                        for i, u in enumerate(batch_urls, 1)
                    }
                    try:
                        for fut in as_completed(futures):
                            ok, err = fut.result()
                            if ok:
                                ok_count += 1
                            else:
                                failures.append((futures[fut], err or "unknown error"))
                            if _CANCEL_LATCH.is_set():
                                for f in futures:
                                    f.cancel()
                                break
                    except KeyboardInterrupt:
                        log("\n! interrupted — waiting for running downloads to finish…")
                        pool.shutdown(wait=False, cancel_futures=True)
                        return 130
                if _CANCEL_LATCH.is_set():
                    raise RunCancelled()

        for ci, s_url in enumerate(scan_urls):
            if ci and args.scan_delay and args.scan_delay > 0:
                # breathe between channels too (latch wait = instant stop)
                if _CANCEL_LATCH.wait(_delay_jitter(args.scan_delay)):
                    _check_cancel()
            _check_cancel()
            s_ok, s_fails = run_scan(s_url, args, ffmpeg_dir)
            ok_count += s_ok
            failures.extend(s_fails)
    except RunCancelled:
        log("\n! stopped by user — completed items are kept; a re-run resumes")
        return 130

    log("-" * 52)
    log(f"summary: {ok_count} succeeded, {len(failures)} failed, "
        f"saved to: {dest}")
    if failures:
        log("failed items:")
        for url, err in failures:
            log(f"  ✗ {url}  ({err[:120]})")
        return 1
    return 0


def main(argv=None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv)
    log(BANNER.format(ver=__version__, ydlp=yt_dlp.version.__version__).lstrip("\n"))
    try:
        return execute(args)
    except KeyboardInterrupt:
        log("\n! interrupted — completed items are kept")
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("\n! interrupted")
        raise SystemExit(130)
