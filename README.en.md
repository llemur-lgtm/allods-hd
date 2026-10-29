# Allods HD

Unofficial patch for **Allods: The Seal of Mystery** (Rage of Mages, 1998) for modern Windows
and wide monitors:

- any resolution from 1024×768 up, e.g. 1600×900 or 1920×1080, fullscreen without black bars;
- the interface adapted to the new screen size;
- 8 spell hotkeys instead of 4, kept across game restarts;
- rendering through [cnc-ddraw](https://github.com/FunkyFr3sh/cnc-ddraw): correct colors, no
  slowdowns or flicker on Windows 10/11.

[Русская версия](README.md)

## Supported version

Only the **Russian GOG release** is supported for now. The patcher checks `ROM.EXE` by its
checksum and refuses any other file. Other editions (Steam, the 1998 CD, the English Rage of
Mages) have a different `ROM.EXE`; if you own one and can help with testing, please open an
issue.

## Installation

1. Download the archive from [Releases](../../releases) and unpack it **into the game folder**
   (where `ROM.EXE` is), replacing `ddraw.dll` and `ddraw.ini`.
2. Run `allods-hd-patch.exe` and enter a resolution such as `1920x1080`, or press Enter for
   1600×900.
3. `ROM_HD.EXE` appears next to `ROM.EXE`; play with it. `ROM.EXE` itself is not modified.

With Python 3.8+: copy `game/ddraw.ini` and `third_party/cnc-ddraw/ddraw.dll` into the game
folder and run `python patch.py 1920 1080 --game-dir "path\to\game"`.

Height must be at least 768, width at least 1024 and a multiple of 4. A resolution with the
monitor's aspect ratio, about 1.5–2 times smaller, works best: 1600×900 for 2560×1440,
1366×768 for 1920×1080.

## Changes

- Right sidebar: the stats panel sits at the bottom, the space above it is filled with the
  ornament.
- Spellbook bar: only as wide as the spell slots; the map on both sides is visible and
  clickable.
- Keys:

| Key | Original | Patched |
|---|---|---|
| F1–F4 | help, save, load, — | spells 5–8 |
| F5–F8 | spells 1–4 | spells 1–4 |
| Ctrl + F1…F8 | — / assign a spell | assign a spell |
| F9 | — | help (key list) |
| F11 | — | save game |
| F12 | debug frame counter | load game |
| C | open the book to pick a spell | cast the selected spell, or open the book if none |

Hotkeys are stored in `HKEY_CURRENT_USER\Software\1C\Allods HD`, value `SpellHotkeys`.
The in-game help still lists F1–F3 for help, save and load.

## Uninstall

Delete `ROM_HD.EXE`; to restore the original rendering, delete `ddraw.dll` and `ddraw.ini`.

## Credits and license

[cnc-ddraw](https://github.com/FunkyFr3sh/cnc-ddraw) by FunkyFr3sh (MIT, see
`third_party/cnc-ddraw`). This project is under the [MIT license](LICENSE). Allods belongs to
its rights holders; this repository contains none of the game's files.
