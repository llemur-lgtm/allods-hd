# Technical notes

All addresses are virtual addresses in `ROM.EXE` of the Russian GOG release
(MD5 `e9c4ceaa3a9ca255289a87ee9a058d91`, image base `0x400000`). Every patch site is checked
against its original bytes before it is changed, so a different executable is rejected instead
of being corrupted.

## Free space for new code

| Area | Range | Why it is free |
|---|---|---|
| `CAVE` | `0x596720–0x5967FF` | zero padding at the end of `.text`; the section's virtual size is raised to cover it |
| `DEAD1` | `0x4B0910–0x4B0A15` | spellbook bar ornaments; skipped once the slot offset is forced to 0 |
| `DEAD2` | `0x46A7F6–0x46A8CC` | loading of the 800×600 interface bitmaps; unreachable when height > 600 |
| slot table | `0x631D40–0x631D5F` | zero-filled tail of `.data`; the section's virtual size is raised to cover it |

## Resolution

The video init code picks 640×480, 800×600 (`-800`) or 1024×768 (`-1024`, also read from the
registry) with `mov ecx, W / mov ebp, H` in five places (`0x4718C1` … `0x47195A`). All of them
get the custom size, so the game always runs at it and the ≤ 600 px interface code paths are
never used. The interface is mostly laid out relative to the screen size
(`[0x5EA208]` width, `[0x5EA20C]` height, `[0x5EA210]` = (width − 640) / 2).

## Right sidebar

The sidebar is drawn for a 768 px tall screen: minimap, buttons, portrait, ornament
(`extra1024l/r`) and the stats panel, which the lower sidebar window bottom-aligns.

- `0x492C43` (lower sidebar window paint): the single ornament draw is replaced by a routine
  that repeats the ornament from y = 480 down to `height − stats height`.
- `0x40C986` (main loop): the 16 px left strip of the stats panel is moved down by
  `height − 768`.

## Spellbook bar

- `0x41E0DD`: the map's visible-row count no longer stops at an open spellbook, so the map is
  rendered under the bar row.
- `0x4763C8`: `ClipCursor` no longer limits the cursor to above an open spellbook.
- `0x4BCBA8` (`Window::Move`): a full-width move of the spellbook window (vtable `0x59AE50`) is
  turned into a slot-sized one centered at `(width − 640) / 2`.
- `0x4B08F7`, `0x4B0C4F`: the slot offset inside the bar becomes 0 (draw and hit-test), the
  same layout the game uses for its own 480 px wide bar. This also skips the ornaments.

## Spell hotkeys

The spellbook window keeps 4 hotkey slots at `[this+0x64..0x70]`, followed by another field.
Every access is redirected to an 8-entry table at `0x631D40` (slots 0–3 = F5–F8, 4–7 = F1–F4):
the three constructors, the icon label loop (`"F%d"`), the "slot has a spell" check, the slot
read in the hotkey handler (message `0x417`) and the assign / de-duplicate loops.

- Map key handler (`switch (vk − 8)` at `0x40F46B`): case 10 (F12, a debug overlay toggle) is
  reused for F1–F4, which run the F5–F8 code with slot = vk − 0x70 + 4.
- Main window key handler (`switch (vk − 8)` at `0x472BB5`): F1–F4 are forwarded to the map
  like F5–F8; help / save / load move to F9 / F11 / F12. F10 arrives as `WM_SYSKEYDOWN` and
  is not used.
- The slot table is read from `HKCU\Software\1C\Allods HD\SpellHotkeys` (binary, 8 dwords)
  when the spellbook is created and written there on every assignment.

## C key

`0x40F755` originally issues map command 5 (open the book to pick a spell) when the book is
closed. Now, if the book has a selected spell (`[spellbook+0x60] != −1`), it issues command 9
(cast the selected spell, as F5–F8 do); otherwise it behaves as before.
