# 🎤 SingFross

A karaoke game built with Python and pygame, supporting the **UltraStar song format** — compatible with thousands of community songs from [usdb.animux.de](https://usdb.animux.de).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![pygame](https://img.shields.io/badge/pygame-2.x-green)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey?logo=apple)

---

## Features

- 🎵 **Song library browser** — sort by title, artist, BPM, or year; search in real time
- 🔍 **YouTube & USDB search** — find and download songs directly from the game
- 🎙️ **Pitch detection** — real-time microphone input with note scoring
- 🌟 **Vocal separation** (optional) — mute/lower the vocal track via [Demucs](https://github.com/facebookresearch/demucs), so you sing over the instrumental
- 🎬 **Gameplay screen** — scrolling note highway, configurable transparency, lyrics on/off toggle
- 📥 **Lyric fetcher** — download timed lyrics from YouTube and convert to UltraStar format automatically
- 🖼️ **Cover art** — auto-download from iTunes for any song in your library

---

## Requirements

- Python 3.10+
- macOS (tested on macOS 14 Sonoma)

### Install dependencies

```bash
pip install pygame yt-dlp requests pygame
```

**Optional — for vocal separation:**
```bash
pip install demucs
brew install ffmpeg      # required by yt-dlp and demucs
```

---

## Setup

```bash
git clone https://github.com/rfrossard/SingFross.git
cd SingFross

# Copy and fill in your credentials
cp .env.example .env
# Edit .env with your usdb.animux.de account (needed to browse/download USDB songs)
```

---

## Running

```bash
python singfross.py
```

---

## Adding Songs

SingFross uses the **UltraStar `.txt` format**, compatible with Vocaluxe, USDX, and most karaoke editors.

Each song lives in its own folder:
```
songs/
  Artist - Title/
    song.txt      ← UltraStar note file (required)
    audio.mp3     ← Audio file (optional)
    cover.jpg     ← Album art (optional)
```

### Ways to add songs

| Method | How |
|--------|-----|
| **In-game import** | Song Select → press `I` → pick a folder in Finder |
| **In-game search** | Search screen → search by title/artist → Download button |
| **Manual** | Drop a song folder into `songs/` → press `R` to refresh |

### Where to find songs

- [usdb.animux.de](https://usdb.animux.de) — largest community database (free account required)
- [ultrastar-es.org](https://ultrastar-es.org)
- GitHub: search `ultrastar songs pack`

---

## Gameplay Controls

### Song Select
| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate songs |
| `Enter` / `Space` | Sing selected song |
| `TAB` | Cycle sort mode |
| `I` | Import song folder |
| `R` | Refresh library |
| Type anything | Search |

### In-Game
| Key | Action |
|-----|--------|
| `H` | Cycle highway transparency (100% → 78% → 51% → 24% → 0%) |
| `L` | Toggle lyrics on/off |
| `[` / `]` | Lower / raise vocal volume |
| `M` | Mute/unmute vocals |
| `Esc` | Return to song select |

---

## Vocal Separation

If [Demucs](https://github.com/facebookresearch/demucs) is installed, SingFross will automatically separate the vocals from the instrumental when you start a song. This lets you:

- Sing over a clean instrumental track
- Adjust or mute the original vocals with `[` `]` `M`

Separation runs in the background on first play and is cached for subsequent plays.

---

## Project Structure

```
singfross.py          ← Entry point
engine/
  song_parser.py      ← UltraStar .txt parser
  audio_player.py     ← pygame audio (dual-channel for vocal separation)
  vocal_separator.py  ← Demucs wrapper
  pitch_detector.py   ← Microphone pitch detection
  scorer.py           ← Note accuracy scoring
  usdb_client.py      ← USDB search & download
  youtube_client.py   ← YouTube search, download & subtitle conversion
  config.py           ← Settings persistence
screens/
  menu.py             ← Main menu
  song_select.py      ← Song library browser
  search_screen.py    ← YouTube / USDB search
  gameplay.py         ← Singing screen
  results.py          ← Score screen
ui/
  components.py       ← Reusable UI widgets
  theme.py            ← Colors, sizes, constants
  fonts.py            ← Font loader
assets/               ← Fonts, icons, logo
songs/                ← Your song library (gitignored)
```

---

## Credits

Built with:
- [pygame](https://www.pygame.org)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Demucs](https://github.com/facebookresearch/demucs) by Meta Research
- UltraStar song format by the [UltraStar Deluxe](https://usdx.eu) community

Song files are **not included** in this repository. Download them from the community sources listed above.
