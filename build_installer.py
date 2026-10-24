#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_installer.py — build the Windows installable version of
YT-Batch-Downloader-Mistu (GUI app).

End product:
  dist/YT-Batch-Downloader-Mistu-<version>-setup.exe   (Inno Setup installer)

The installer ships:
  app/       standalone CPython (Windows, includes tkinter) + yt-dlp & libs
  ffmpeg/    ffmpeg.exe + ffprobe.exe
  yt_batch_downloader_mistu.py   the download engine (also usable as a CLI)
  mistu_gui.py                   the Tkinter GUI

Requirements: Python 3.8+ to run this script, an internet connection, and
Inno Setup 6 (winget install JRSoftware.InnoSetup — installed automatically
if missing, when --install-inno is passed).

Usage (run on Windows):
  python build_installer.py            # -> dist ...-setup.exe
  python build_installer.py --no-compile  # stage only (skip Inno compile)
  python build_installer.py --clean
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

APP_NAME = "YT-Batch-Downloader-Mistu"
ENGINE = "yt_batch_downloader_mistu.py"
GUI = "mistu_gui.py"
VERSION = "2.9.3"

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(ROOT, "build")
DOWNLOADS = os.path.join(BUILD_DIR, "downloads")
STAGE = os.path.join(BUILD_DIR, "installer", APP_NAME)
DIST = os.path.join(ROOT, "dist")

APP = os.path.join(STAGE, "app")
FFMPEG = os.path.join(STAGE, "ffmpeg")

PSA_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
PSA_PREFERRED = "3.13"
ZIP_CHUNK = 1024 * 512


# ----------------------------------------------------------------- helpers --
def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def fetch(url: str, dest_file: str, desc: str) -> None:
    if os.path.isfile(dest_file) and os.path.getsize(dest_file) > 0:
        print(f"  cached: {os.path.basename(dest_file)}")
        return
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    print(f"  downloading {desc} ...")
    print(f"    {url}")
    tmp = dest_file + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "yt-batch-downloader-mistu-build/1.2"})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(ZIP_CHUNK)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done * 100.0 / total:5.1f}%  "
                      f"{done / 1e6:7.1f} / {total / 1e6:7.1f} MB", end="", flush=True)
        print()
    os.replace(tmp, dest_file)


def extract_zip(zip_path: str, dest_dir: str, wanted=None) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            base = os.path.basename(member.filename.replace("\\", "/"))
            if member.is_dir() or not base:
                continue
            if wanted and base not in wanted:
                continue
            with zf.open(member) as src, open(os.path.join(dest_dir, base), "wb") as out:
                shutil.copyfileobj(src, out)


def extract_tar(tar_path: str, dest_dir: str) -> None:
    """Extract with symlinks resolved (safe on NTFS targets)."""
    with tempfile.TemporaryDirectory(prefix="mistu-extract-") as tmp:
        with tarfile.open(tar_path, "r:*") as tf:
            tf.extractall(tmp, filter="tar")
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(tmp, dest_dir, symlinks=False, dirs_exist_ok=True)


# ----------------------------------------------------------- python (psa) ---
def find_windows_python_asset() -> str:
    step("1a. Discover standalone CPython (Windows, with tkinter)")
    last = "<no message>"
    for attempt in range(3):
        try:
            req = urllib.request.Request(PSA_API, headers={"User-Agent": "mistu-build/1.2"})
            with urllib.request.urlopen(req) as resp:
                release = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"error: GitHub API HTTP {exc.code}")
        assets = release.get("assets")
        if not isinstance(assets, list) or not assets:
            last = str(release.get("message", "<no assets>"))
            print(f"  API said: {last[:120]}")
            if attempt < 2:
                time.sleep(5)
            continue
        names = [a.get("name", "") for a in assets]
        urls = {a.get("name", ""): a.get("browser_download_url") for a in assets}
        rx = (rf"cpython-{re.escape(PSA_PREFERRED)}\.\d+\+[0-9.]*-x86_64-pc-windows-msvc"
              r"-install_only\.tar\.gz")
        picks = [n for n in names if re.fullmatch(rx, n)]
        if not picks:
            rx_any = (r"cpython-\d+\.\d+\.\d+\+[0-9.]*-x86_64-pc-windows-msvc"
                      r"-install_only\.tar\.gz")
            picks = [n for n in names if re.fullmatch(rx_any, n)]
        if not picks:
            raise SystemExit("error: no Windows python-build-standalone asset found")
        name = sorted(picks)[-1]
        print(f"  selected: {name}")
        fetch(urls[name], os.path.join(DOWNLOADS, "python-standalone-win64.tar.gz"),
              "CPython standalone (win x86_64, includes tkinter)")
        return name
    raise SystemExit(f"error: could not list GitHub assets ({last[:120]})")


def stage_python() -> None:
    step("1. Embedded Python (standalone, includes tkinter)")
    find_windows_python_asset()
    if os.path.isdir(os.path.join(STAGE, "app")):
        shutil.rmtree(os.path.join(STAGE, "app"))
    extract_tar(os.path.join(DOWNLOADS, "python-standalone-win64.tar.gz"),
                os.path.join(STAGE, "app"))
    py_exe = os.path.join(APP, "python", "python.exe")
    if not os.path.isfile(py_exe):
        raise SystemExit(f"error: {py_exe} missing after extraction")
    print(f"  python: {os.path.relpath(py_exe, ROOT)}")


def install_packages() -> None:
    step("2. yt-dlp & companion packages")
    py_exe = os.path.join(APP, "python", "python.exe")
    use = os.environ.get("MISTU_PYTHON")
    if use:  # only informative; PSA is pinned by asset
        print(f"  note: MISTU_PYTHON={use} is ignored in installer builds "
              "(standalone CPython per PSA asset)")
    try:
        subprocess.run([py_exe, "-m", "ensurepip", "--upgrade"], check=True,
                       stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("  ensurepip failed — trying existing pip")
    pkgs = list(PIP_PACKAGES)
    while True:
        rc = subprocess.run([py_exe, "-m", "pip", "install", "--no-warn-script-location",
                             "--upgrade", *pkgs]).returncode
        if rc == 0:
            break
        if "brotli" in pkgs:
            print("  retrying without brotli (optional dep)")
            pkgs.remove("brotli")
            continue
        raise SystemExit("error: pip install failed")
    subprocess.run([py_exe, "-c",
                    "import yt_dlp, mutagen; import tkinter;"
                    "print('  yt-dlp', yt_dlp.version.__version__, '| tkinter OK')"],
                   check=True)


PIP_PACKAGES = ["yt-dlp", "brotli", "certifi", "mutagen", "websockets"]
FFMPEG_URL = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl.zip")


def stage_ffmpeg() -> None:
    step("3. FFmpeg (Windows)")
    ff_zip = os.path.join(DOWNLOADS, "ffmpeg-win64.zip")
    fetch(FFMPEG_URL, ff_zip, "FFmpeg Win64 (yt-dlp/FFmpeg-Builds)")
    if os.path.isdir(FFMPEG):
        shutil.rmtree(FFMPEG)
    wanted = {"ffmpeg.exe", "ffprobe.exe"}
    extract_zip(ff_zip, FFMPEG, wanted=wanted)
    for exe in sorted(wanted):
        if not os.path.isfile(os.path.join(FFMPEG, exe)):
            raise SystemExit(f"error: {exe} not staged")
    print("  ffmpeg.exe + ffprobe.exe staged")


def stage_app_files() -> None:
    step("4. Program files")
    for name in (ENGINE, GUI, "README.md"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(STAGE, name))
    # visual identity: app icon + Inno wizard art (window icon, shortcuts)
    assets_src = os.path.join(ROOT, "assets")
    if not os.path.isfile(os.path.join(assets_src, "icon.ico")):
        raise SystemExit("error: assets/icon.ico missing — see assets/ in the repo")
    shutil.copytree(assets_src, os.path.join(STAGE, "assets"),
                    ignore=shutil.ignore_patterns("preview*.png"))
    cli_cmd = os.path.join(STAGE, "YT-Batch-Downloader-Mistu-CLI.cmd")
    with open(cli_cmd, "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(
            "@echo off\r\n"
            "setlocal\r\n"
            "set \"SCRIPT_DIR=%~dp0\"\r\n"
            "set \"PYTHONUTF8=1\"\r\n"
            "set \"PYTHONIOENCODING=utf-8\"\r\n"
            "set \"PATH=%SCRIPT_DIR%ffmpeg;%PATH%\"\r\n"
            f"\"%SCRIPT_DIR%app\\python\\python.exe\" \"%SCRIPT_DIR%{ENGINE}\" %*\r\n"
            "exit /b %errorlevel%\r\n"
        )
    print(f"  {ENGINE} + {GUI} + CLI launcher staged")


# --------------------------------------------------------------- inno ------
def find_iscc() -> str | None:
    cands = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LocalAppData", ""),
                     "Programs", "Inno Setup 6", "ISCC.exe"),
        shutil.which("iscc") or "",
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def ensure_iscc(auto_install: bool) -> str:
    iscc = find_iscc()
    if iscc:
        return iscc
    if not auto_install:
        raise SystemExit(
            "error: Inno Setup 6 not found.\n"
            "  install with:  winget install -e --id JRSoftware.InnoSetup\n"
            "  then re-run, or pass --install-inno to let this script do it.")
    step("0. Installing Inno Setup (winget)")
    rc = subprocess.run(["winget", "install", "-e", "--id", "JRSoftware.InnoSetup",
                         "--accept-source-agreements", "--accept-package-agreements",
                         "--silent"]).returncode
    time.sleep(3)
    iscc = find_iscc()
    if not iscc:
        raise SystemExit("error: Inno Setup still missing after winget install "
                         f"(winget rc={rc}). Install it manually and re-run.")
    print(f"  Inno Setup installed: {iscc}")
    return iscc


def compile_installer(iscc: str) -> None:
    step("5. Compile installer (Inno Setup)")
    iss = os.path.join(ROOT, "YT-Batch-Downloader-Mistu.iss")
    os.makedirs(DIST, exist_ok=True)
    subprocess.run([iscc, f"/DAppVersion={VERSION}", "/Qp", os.path.basename(iss)],
                   cwd=ROOT, check=True)
    # OutputBaseFilename uses the AppName from the .iss ("Mistus Batch YT Downloader")
    out = os.path.join(DIST, f"Mistus Batch YT Downloader-{VERSION}-setup.exe")
    if not os.path.isfile(out):
        raise SystemExit(f"error: installer not produced at {out}")
    print(f"  installer: {out}  ({os.path.getsize(out) / 1e6:.1f} MB)")


def clean() -> None:
    for d in (BUILD_DIR, DIST):
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"removed: {d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="wipe build/ and dist/, then exit")
    ap.add_argument("--no-compile", action="store_true", help="stage without running Inno Setup")
    ap.add_argument("--install-inno", action="store_true",
                    help="auto-install Inno Setup 6 via winget when missing")
    args = ap.parse_args()

    if args.clean:
        clean()
        return 0

    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)

    stage_python()
    install_packages()
    stage_ffmpeg()
    stage_app_files()

    if not args.no_compile:
        iscc = ensure_iscc(args.install_inno)
        compile_installer(iscc)
        print(f"\nDONE. Distribute Mistus Batch YT Downloader-{VERSION}-setup.exe — "
              "installs GUI + CLI + bundled Python/FFmpeg, creates Start-Menu icons.")
    else:
        print(f"\nDONE (staged only): {STAGE}  — compile with Inno Setup yourself or "
              "re-run without --no-compile.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"\nbuild failed: {getattr(exc, 'cmd', exc)} "
                         f"returned {exc.returncode}\n")
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        sys.stderr.write(f"\nbuild failed: download error: {getattr(exc, 'reason', exc)}\n")
        raise SystemExit(1)
