# Mistus Batch YT Downloader

A **YouTube batch downloader & channel scanner** for Windows, powered by the
[**yt-dlp**](https://github.com/yt-dlp/yt-dlp) engine, distributed as a
**Windows installer** (GUI + CLI in one). The installer ships its own Python
and FFmpeg — nothing else needs to be installed.

```
====================================================
  YT-Batch-Downloader-Mistu  v2.1.0
  YouTube batch downloader • channel scanner •  engine: yt-dlp
====================================================
```

---

## Installing

Double-click `YT-Batch-Downloader-Mistu-<version>-setup.exe` and follow the
wizard. It will:

- install the GUI app (embedded CPython 3.13 with tkinter + yt-dlp + FFmpeg) into
  `C:\Program Files\YT-Batch-Downloader-Mistu\`
- create **Start-Menu** shortcuts (GUI, CLI, Uninstall) and an optional desktop icon
- optionally add the **CLI** to the system `PATH` (unticked by default)

Uninstall through Windows "Apps & Features" or the Start-Menu item
(removes the PATH entry automatically).

## Using the GUI

1. Paste **channel URLs** or **video URLs** (one per line) or load a `.txt` list.
   - channel URLs (`youtube.com/@name`) are **scanned** automatically
2. Pick options (quality `audio`/`1080…`, MP3/M4A…, include Shorts, min/max
   video length, scan delay, parallel jobs, cookies.txt)
3. **Music mode**: tick "Music mode" and (optionally) fill "Artist"/"Song title"
    to download best audio as M4A with cover art embedded and tagged metadata.
4. Press **▶ Start**. Live activity log shows progress; press **■ Stop** to
   stop after the current item; **📂** opens the output folder.

### Channel scan mode (default for channel URLs)

For **every long video** of the channel it saves:

```
<output>/
├── Audio/       1_Some_Video_Title.mp3 …      (best audio + metadata)
├── Thumbnail/   1_Some_Video_Title.png …      (converted to PNG)
└── Text File/   1_Some_Video_Title.txt …      (URL, title, channel, date,
                    duration, views, description, tags, music info,
                    transcription from captions)
```

- `--shorts` (GUI checkbox) adds the channel's Shorts
- min/max length filters (`--min-length` / `--max-length`, e.g. `2:00`, `8:00`)
- `--playlist-limit N` caps the number of items
- `--scan-delay SEC` pauses between videos to avoid bot rate-limits
- re-running a scan **resumes** — already saved items are skipped

### Batch mode (video/playlist URLs)

Normal videos/playlists download with the classic batch logic: quality presets,
`-j` parallel downloads, an auto `downloaded.txt` archive for resume, subtitles
and embedded thumbnails/metadata.

## Using the CLI

`yt_batch_downloader_mistu.py` is the same engine headless — run it through the
installed launcher (`YT-Batch-Downloader-Mistu-CLI.cmd`) or directly:

```bat
YT-Batch-Downloader-Mistu-CLI.cmd https://www.youtube.com/@SomeChannel
YT-Batch-Downloader-Mistu-CLI.cmd -q 1080 -j 3 --no-playlist url1 url2 list.txt
YT-Batch-Downloader-Mistu-CLI.bat -q audio --audio-format mp3 --min-length 2:00 --max-length 8:00 https://www.youtube.com/@SomeChannel --playlist-limit 50
```

Any Python 3.9+ on Windows can also run it directly with `pip install -r requirements.txt`
(FFmpeg must be available on PATH then — bundled only in the installer).

---

## Building the installer

Requires **Python 3.8+** on the build machine, internet access, and
**Inno Setup 6** (`winget install -e --id JRSoftware.InnoSetup`; the build
script auto-installs it with `--install-inno`).

```bat
python build_installer.py                 :: -> dist\YT-Batch-Downloader-Mistu-<ver>-setup.exe
python build_installer.py --no-compile    :: stage build\installer\ only
python build_installer.py --clean         :: wipe build\ and dist\
```

Steps: fetch a **standalone CPython (Windows, includes tkinter)**, install
yt-dlp (+ brotli, certifi, mutagen, websockets) *inside it*, fetch **FFmpeg
Win64**, stage program files, then compile `YT-Batch-Downloader-Mistu.iss`
with Inno Setup. Downloads are cached in `build\downloads\` between runs.

Or double-click **`build.bat`**.

---

## Notes & troubleshooting

- **Rate limiting**: big scans can hit `429` / "confirm you're not a bot" —
  raise *delay* (`--scan-delay 3`), wait a while, or select a `cookies.txt`
  exported from a logged-in browser (GUI field or `--cookies`).
- **Live streams** are skipped; **age-restricted** videos need cookies.
- Files are named `Title [VideoID].ext`; resumable file names are
  `N_Title .mp3/.png/.txt` in scan mode.
- **Updating yt-dlp**: use the GUI button "⬆ Update yt-dlp" or run
  `YT-Batch-Downloader-Mistu-CLI.cmd --update-ytdlp` (updates via pip in the
  bundled Python).
- The engine is CLI-agnostic: pass `--help` to see all options.

## Cookies (avoiding YouTube blocks)

YouTube throttles anonymous bulk access with `429 Too Many Requests` /
"confirm you're not a bot" errors — especially for big channels and repeated
scans from one IP. Passing a `cookies.txt` exported from your **logged-in**
browser makes requests look like your normal account activity and almost
always clears these errors.

1. Install a cookie exporter in your browser (any one of these):
   **Get cookies.txt LOCALLY** (Chrome), **cookies.txt** (Firefox add-on),
   or **Cookie-Editor** (Chrome/Edge/Firefox, "Export → Netscape").
2. Log into youtube.com in that browser (a normal Google account is fine;
   a burned/throwaway account is safer than your main one).
3. While on youtube.com, export the cookies as **Netscape format** and save
   them as `cookies.txt` (make sure the file's first line is
   `# Netscape HTTP Cookie File`).
4. In the GUI, paste the full path into the
   **"cookies.txt (optional)"** field (or pick it with the `…` button); on the
   CLI add `--cookies C:\path\to\cookies.txt`.
5. Keep cookies working:
   - **Never share** the file — it can be used to hijack the session.
   - Re-export every few weeks (cookies expire / rotate).
   - If you use 2FA or "sign-in with phone" only, still export from the same
     browser you logged in with.
   - Use `--scan-delay 2-3` between items for very large channels; cookies +
     a delay together is the most reliable combination.
   - Downloads **remember** which items already succeeded (downloaded.txt
     archive), so after a 429 you can just re-run later and it resumes.

## Credits

- Engine: [yt-dlp](https://github.com/yt-dlp/yt-dlp) (UNLICENSE)
- Python: [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
- FFmpeg builds: [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds)
- Installer: [Inno Setup](https://jrsoftware.org/isinfo.php)
