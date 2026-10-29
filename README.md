# Mistus Batch YT Downloader

A simple Windows app to batch-download YouTube videos and channels.
Downloads best-quality **MP3 audio**, **thumbnails**, and a **text info file** for every video.

```
Mistus Batch YT Downloader v2.9.7
```

## Install

Go to [Releases](https://github.com/mistu01/Mistus-YT-Batch-Downloader/releases), download the `-setup.exe` and run it. Done.

## How to use

1. Paste a channel / video / playlist link (one per line)
2. Choose naming format: **Regular (`1_Title`)** or **Prefix only (`1.mp3`)**
3. Press **▶ START**
4. Press **■ STOP** to stop anytime

Files are saved to your download folder:

```
Audio/       1_Title.mp3 (or 1.mp3 with Prefix-only)
Thumbnail/   1_Title.png (or 1.png with Prefix-only)
Text File/   1_Title.txt (or 1.txt with Prefix-only)
```

Re-running the same folder continues numbering and skips already-downloaded items.

## Blocks / cookies

If downloads fail slowly or hit "too many requests", export cookies from your browser ([extension](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)), then pick the file in the app's cookies field.
