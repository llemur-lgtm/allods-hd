"""Allods HD: widescreen and hotkey patch for Allods: The Seal of Mystery (Rage of Mages).

Creates ROM_HD.EXE next to the original ROM.EXE of the Russian GOG release; ROM.EXE itself
is never modified.

    python patch.py                 # 1600x900, game folder = current folder
    python patch.py 1920 1080       # custom resolution
    python patch.py --game-dir "C:\\GOG Games\\Allods"

Changes:
  * custom resolution: every video mode of the game (-640 / -800 / -1024) runs at WIDTHxHEIGHT;
  * right sidebar: the stats panel sits at the bottom and the gap above it is filled with
    copies of the ornament under the portrait;
  * spellbook bar: only as wide as the spell slots (the game's own narrow layout), the map is
    rendered and clickable on both sides of it;
  * 8 spell hotkeys: F5..F8 as before plus F1..F4 (Ctrl+key assigns); help / save / load move
    from F1 / F2 / F3 to F9 / F11 / F12; hotkeys are kept across game restarts
    (HKCU\\Software\\1C\\Allods HD, value SpellHotkeys);
  * C casts the spell selected in the book; with nothing selected it opens the book as before;
  * the cursor and the item in hand no longer flicker while they move.
"""
import argparse
import hashlib
import os
import struct
import sys

__version__ = "1.0.2"

SOURCE_NAME, TARGET_NAME = "ROM.EXE", "ROM_HD.EXE"
SOURCE_MD5 = "e9c4ceaa3a9ca255289a87ee9a058d91"  # ROM.EXE of the Russian GOG release
DEFAULT_SIZE = (1600, 900)

IMAGE_BASE = 0x400000
TEXT_RVA, TEXT_RAW = 0x1000, 0x400

# Free space for new code:
#   CAVE  - zero padding at the end of .text;
#   DEAD1 - spellbook bar ornaments, skipped once the bar is slot-sized (see SPELLBOOK_OFFSET);
#   DEAD2 - loading of the 800x600 interface bitmaps, unreachable with height > 600.
CAVE = (0x596720, 0x596800)
DEAD1 = (0x4B0910, 0x4B0A16)
DEAD2 = (0x46A7F6, 0x46A8CD)

# Game globals and functions used by the new code
SCREEN_WIDTH_OFFSET = "10 a2 5e 00"   # (width - 640) / 2
SCREEN_HEIGHT = "0c a2 5e 00"
CTRL_PRESSED = "58 b5 5e 00"
ORNAMENT_STRIP = "60 f9 5e 00"        # extra1024l: 16 px left strip, drawn by the main loop
ORNAMENT_PANEL = "64 f9 5e 00"        # extra1024r: the ornament, drawn by the lower sidebar panel
STATS_PANEL = "08 f9 5e 00"           # stats panel bitmap
SPELLBOOK_VTABLE = "50 ae 59 00"
IS_SPELLBOOK_OPEN = 0x41DDEA          # map window methods
MAP_COMMAND = 0x41B439
SPELLBOOK_HAS_SPELL = 0x4B0CE0
REG_CREATE_KEY, REG_CLOSE_KEY = "e4 28 63 00", "c4 28 63 00"  # import table entries
REG_QUERY_VALUE, REG_SET_VALUE = "c8 28 63 00", "c0 28 63 00"


class PatchError(Exception):
    pass


# --- helpers ---------------------------------------------------------------------------------

def va2off(va):
    return va - IMAGE_BASE - TEXT_RVA + TEXT_RAW


def le32(value):
    return struct.pack("<I", value).hex()


def rel32(src_va, dst_va):
    return struct.pack("<i", dst_va - (src_va + 5))


def assemble(parts, va=0):
    """Tiny assembler for pre-encoded x86.

    parts: (hex bytes, label defined at their start, (target, "rel8" | "rel32") patched into
    their last bytes). A target is a label name or an absolute address; absolute targets need
    the address va the code will be placed at.
    """
    code, labels, fixups = bytearray(), {}, []
    for hexstr, label, ref in parts:
        if label:
            labels[label] = len(code)
        code += bytes.fromhex(hexstr)
        if ref:
            fixups.append((len(code), *ref))
    for end, target, kind in fixups:
        rel = target - (va + end) if isinstance(target, int) else labels[target] - end
        if kind == "rel32":
            code[end - 4:end] = struct.pack("<i", rel)
        else:
            assert -128 <= rel < 128
            code[end - 1] = rel & 0xFF
    return bytes(code)


class Image:
    def __init__(self, data):
        self.data = bytearray(data)

    def put(self, va, original, new):
        off = va2off(va)
        if self.data[off:off + len(original)] != original:
            raise PatchError(f"неожиданные байты по адресу {va:#x}")
        self.data[off:off + len(new)] = new

    def hook(self, kind, site_va, target_va, original):
        """Replace the code at site_va by call/jmp target_va, padded with nops."""
        code = kind + rel32(site_va + len(kind) - 1, target_va)
        self.put(site_va, original, code + b"\x90" * (len(original) - len(code)))

    def place(self, area, code, fill_check=None):
        start, end = area
        if start + len(code) > end:
            raise PatchError(f"не хватает места по адресу {start:#x}")
        off = va2off(start)
        if fill_check is not None and self.data[off:off + len(code)] != fill_check * len(code):
            raise PatchError(f"область по адресу {start:#x} занята")
        self.data[off:off + len(code)] = code

    def set_section_vsize(self, index, name, old, new):
        pe = struct.unpack_from("<I", self.data, 0x3C)[0]
        header = pe + 24 + struct.unpack_from("<H", self.data, pe + 20)[0] + 40 * index
        if self.data[header:header + len(name)] != name:
            raise PatchError(f"секция {name!r} не найдена")
        if old is not None and struct.unpack_from("<I", self.data, header + 8)[0] != old:
            raise PatchError(f"у секции {name!r} неожиданный размер")
        struct.pack_into("<I", self.data, header + 8, new)


# --- resolution ------------------------------------------------------------------------------

# "mov ecx, W / mov ebp, H" in every branch of the video init code (-800 / -1024 from the
# command line or the registry, 640x480 by default)
RESOLUTION_SITES = [
    (0x4718C1, "b9 20 03 00 00 bd 58 02 00 00"),
    (0x4718ED, "b9 00 04 00 00 bd 00 03 00 00"),
    (0x47192C, "b9 20 03 00 00 bd 58 02 00 00"),
    (0x47194E, "b9 00 04 00 00 bd 00 03 00 00"),
    (0x47195A, "b9 80 02 00 00 bd e0 01 00 00"),
]


def patch_resolution(img, width, height):
    code = b"\xb9" + struct.pack("<I", width) + b"\xbd" + struct.pack("<I", height)
    for va, original in RESOLUTION_SITES:
        img.put(va, bytes.fromhex(original), code)


# --- right sidebar ---------------------------------------------------------------------------

# Main loop: "mov ecx,[ebp-0x44] / lea edx,[ecx+eax+0x1e0]" = y of the stats panel's left
# strip, right below the ornament
STATS_STRIP_SITE = (0x40C986, "8b 4d bc 8d 94 01 e0 01 00 00")
# Lower sidebar panel (480..height): ornament->draw(x=[esp+0x20], y=edx, 0, 0, 0) at its top
PANEL_SITE = (0x492C43, "8b 01 6a 00 6a 00 6a 00 52 8b 54 24 30 52 ff 50 18")


def stats_strip_code():
    """y of the stats panel strip, moved down by height - 768."""
    return assemble([
        ("8b 4d bc", None, None),                   # mov ecx, [ebp-0x44]
        ("8d 94 01 e0 fe ff ff", None, None),       # lea edx, [ecx+eax+0x1e0-0x300]
        ("03 15 " + SCREEN_HEIGHT, None, None),     # add edx, [screen height]
        ("c3", None, None),
    ])


def panel_code():
    """Draw the ornament at y, then repeat it down to the bottom-aligned stats panel.

    Called as `push y / call` with ecx = ornament bitmap; x is the caller's [esp+0x20].
    """
    return assemble([
        ("53 56 55", None, None),                   # push ebx / push esi / push ebp
        ("8b f1", None, None),                      # mov esi, ecx               (bitmap)
        ("8b 5c 24 10", None, None),                # mov ebx, [esp+0x10]        (y)
        ("8b 6c 24 34", None, None),                # mov ebp, [esp+0x34]        (x)
        ("e8 00 00 00 00", None, ("draw", "rel32")),  # the original single ornament
        ("8b 0d " + STATS_PANEL, None, None),       # eax = stats->height(0)
        ("6a 00 8b 01 ff 50 24", None, None),
        ("ff 35 " + SCREEN_HEIGHT, None, None),     # [esp] = height - stats height
        ("29 04 24", None, None),
        ("6a 00 8b ce 8b 01 ff 50 24", None, None),  # eax = ornament->height(0)
        ("85 c0 74 00", None, ("done", "rel8")),
        ("03 d8", None, None),                      # add ebx, eax
        ("8d 0c 03 3b 0c 24", "loop", None),        # lea ecx, [ebx+eax] / cmp ecx, [esp]
        ("7e 00", None, ("draw_next", "rel8")),
        ("3b 1c 24 7d 00", None, ("done", "rel8")),
        ("8b 1c 24 2b d8", None, None),             # last copy overlaps the previous one
        ("50 e8 00 00 00 00", "draw_next", ("draw", "rel32")),
        ("58 03 d8 eb 00", None, ("loop", "rel8")),
        ("58 5d 5e 5b c2 04 00", "done", None),
        # draw: ornament->draw(ebp, ebx, 0, 0, 0) and, for the 1024 ornament, its left strip
        ("6a 00 6a 00 6a 00 53 55 8b ce 8b 01 ff 50 18", "draw", None),
        ("3b 35 " + ORNAMENT_PANEL, None, None),
        ("75 00", None, ("ret", "rel8")),
        ("6a 00 6a 00 6a 00 53", None, None),
        ("8d 45 f0 50", None, None),                # x - 0x10
        ("8b 0d " + ORNAMENT_STRIP, None, None),
        ("8b 01 ff 50 18", None, None),
        ("c3", "ret", None),
    ])


# --- spellbook bar ---------------------------------------------------------------------------

# An open spellbook moves the bottom of the rendered map rows and of the cursor clip rectangle
# up to the bar: "je" -> "jmp" leaves only the inventory bar as the limit
MAP_ROWS_SITE = (0x41E0D9, "83 7d fc 00 74 09", "83 7d fc 00 eb 09")
CURSOR_CLIP_SITE = (0x4763C6, "85 c0 74 1d", "85 c0 eb 1d")
# Main loop: black fills next to an open spellbook, for the rows the game no longer draws there;
# with the map rendered under the bar they only leave black areas on top of it
BAR_FILLS_SITE = (0x40C6B8, "83 7d 9c 00 74 51")
BAR_FILLS_DONE = 0x40C76F
# Slots are drawn and hit-tested at window left + (width-640)/2; with a slot-sized window the
# offset is 0, which also skips the ornaments (the game's own narrow layout)
SPELLBOOK_OFFSET_SITES = (0x4B08F7, 0x4B0C4F)
SPELLBOOK_OFFSET = ("8b 3d 10 a2 5e 00", "33 ff 90 90 90 90")
# Window::Move(left, top, right, bottom) prologue; the spellbook is moved before it is shown
WINDOW_MOVE_SITE = (0x4BCBA8, "55 8b ec 51 89 4d fc")
WINDOW_MOVE_CONTINUE = 0x4BCBAF
SPELL_SLOTS_WIDTH = 0x1D0


def window_move_code(va):
    """A full-width move of the spellbook window becomes a slot-sized, centered one."""
    return assemble([
        ("81 39 " + SPELLBOOK_VTABLE, None, None),  # spellbook window?
        ("75 00", None, ("orig", "rel8")),
        ("83 7c 24 04 00", None, None),             # left == 0
        ("75 00", None, ("orig", "rel8")),
        ("81 7c 24 0c e0 01 00 00", None, None),    # right > 480 (not the narrow layout)
        ("7e 00", None, ("orig", "rel8")),
        ("a1 " + SCREEN_WIDTH_OFFSET, None, None),  # left = (width-640)/2
        ("89 44 24 04", None, None),
        ("05 " + le32(SPELL_SLOTS_WIDTH), None, None),  # right = left + slots width
        ("89 44 24 0c", None, None),
        (WINDOW_MOVE_SITE[1], "orig", None),        # the replaced prologue
        ("e9 00 00 00 00", None, (WINDOW_MOVE_CONTINUE, "rel32")),
    ], va)


# --- hotkeys ---------------------------------------------------------------------------------

# The spellbook keeps 4 hotkey slots at [this+0x64..0x70] and another field right after them,
# so all slot code is redirected to an 8-entry table in the zero-filled tail of .data:
# slots 0..3 = F5..F8, slots 4..7 = F1..F4.
DATA_SECTION = (2, b".data", 0x5B8000, 0x79D3C)
SLOTS_VA = 0x631D40
SLOTS = le32(SLOTS_VA)
SLOT_SITES = [
    (0x4B0250, "89 0a 89 4a 04 89 4a 08 89 4a 0c", "fill"),       # constructors: slots = -1
    (0x4B02DD, "89 11 89 51 04 89 51 08 89 51 0c", "fill"),
    (0x4B032E, "89 11 89 51 04 89 51 08 89 51 0c", "fill"),
    (0x4B0B39, "33 d2 33 c0 8d 4b 64 39 31 75 03 8d 50 05 40 83 c1 04 83 f8 04 7c f0", "label"),
    (0x4B0CE8, "83 7c be 64 ff", "is_empty"),
    (0x4B0D0F, "8b 4c be 64 8b 80 d0 00 00 00", "load_ecx"),
    (0x4B0E9A, "89 44 be 64 33 c9 8d 56 64 3b cf 74 0a 39 02 75 06 c7 02 ff ff ff ff"
               " 41 83 c2 04 83 f9 04 7c e9", "assign"),         # Ctrl+F: assign
    (0x4B0ECE, "89 44 be 64 33 c0 8d 4e 64 3b c7 74 0d 8b 11 3b 56 60 75 06 c7 01 ff ff ff ff"
               " 40 83 c1 04 83 f8 04 7c e6", "assign"),
    (0x4B0F05, "8b 44 be 64 85 c0", "load_eax"),                  # F: select the slot's spell
]
# Map key switch on vk - 8: case 10 was F12 (debug overlay), which no longer reaches the map
MAP_KEY_CASE10 = (0x40FCF1, 0x40F500)
MAP_KEY_F1_F4_BYTES = 0x40FD61
MAP_KEY_DONE = 0x40FC47
MAP_KEY_HANDLED = 0x40FCC3
# Main window key switch on vk - 8: F1..F4 go to the map like F5..F8 (case 16);
# F9 / F11 / F12 take help / save / load (cases 12 / 13 / 14). F10 is a Windows system key.
MAIN_KEY_BYTES = 0x472EE8
MAIN_KEY_CASES = {0x70: (0x0C, 0x10), 0x71: (0x0D, 0x10), 0x72: (0x0E, 0x10), 0x73: (0x0F, 0x10),
                  0x78: (0x11, 0x0C), 0x7A: (0x14, 0x0D), 0x7B: (0x12, 0x0E)}
# "C": originally Command(5), "open the book to pick a spell"
CAST_KEY_SITE = (0x40F755, "8b 4d b0 e8 8d")
REG_SUBKEY, REG_VALUE = b"Software\\1C\\Allods HD\0", b"SpellHotkeys\0"


def slot_code(vas, load_va, save_va):
    """Slot table accessors; edi = slot index. vas: placement of each routine."""
    return {
        # slots = -1, then the saved hotkeys (eax / ecx / edi preserved)
        "fill": assemble([
            ("57 51 50 83 c8 ff", None, None),
            ("bf " + SLOTS + " b9 08 00 00 00 f3 ab", None, None),
            ("58 59 5f", None, None),
            ("e9 00 00 00 00", None, (load_va, "rel32")),
        ], vas.get("fill", 0)),
        # edx = number shown on spell esi's icon ("F%d"), 0 = none
        "label": assemble([
            ("33 d2 33 c0", None, None),
            ("39 34 85 " + SLOTS, "loop", None),
            ("75 00", None, ("next", "rel8")),
            ("8d 50 05", None, None),               # slots 0..3: F5..F8
            ("83 f8 04 7c 00", None, ("next", "rel8")),
            ("8d 50 fd", None, None),               # slots 4..7: F1..F4
            ("40 83 f8 08 7c 00", "next", ("loop", "rel8")),
            ("c3", None, None),
        ]),
        "is_empty": assemble([("83 3c bd " + SLOTS + " ff c3", None, None)]),
        "load_ecx": assemble([("8b 0c bd " + SLOTS + " 8b 80 d0 00 00 00 c3", None, None)]),
        "load_eax": assemble([("8b 04 bd " + SLOTS + " 85 c0 c3", None, None)]),
        # slots[edi] = eax, the same spell is removed from the other slots, then saved
        "assign": assemble([
            ("89 04 bd " + SLOTS + " 33 c9", None, None),
            ("3b cf 74 00", "loop", ("next", "rel8")),
            ("39 04 8d " + SLOTS + " 75 00", None, ("next", "rel8")),
            ("c7 04 8d " + SLOTS + " ff ff ff ff", None, None),
            ("41 83 f9 08 7c 00", "next", ("loop", "rel8")),
            ("e9 00 00 00 00", None, (save_va, "rel32")),
        ], vas.get("assign", 0)),
    }


def hotkey_storage_code(va):
    """Registry load / save of the slot table (all registers preserved) and the "C" key.
    Returns (code, load_va, save_va, cast_va)."""
    subkey_va = va
    value_va = subkey_va + len(REG_SUBKEY)
    load_va = value_va + len(REG_VALUE)
    open_key = [
        ("60 6a 00 54", None, None),                # pushad / hkey / &hkey
        ("68 " + le32(subkey_va), None, None),
        ("68 01 00 00 80", None, None),             # HKEY_CURRENT_USER
        ("ff 15 " + REG_CREATE_KEY, None, None),
        ("85 c0 75 00", None, ("fail", "rel8")),
    ]
    close_key = [
        ("ff 34 24 ff 15 " + REG_CLOSE_KEY, None, None),
        ("58 61 c3", "fail", None),
    ]
    load = assemble(open_key + [
        ("6a 20 8b c4 50", None, None),             # size = 32, &size
        ("68 " + SLOTS + " 6a 00 6a 00 68 " + le32(value_va), None, None),
        ("ff 74 24 18 ff 15 " + REG_QUERY_VALUE, None, None),
        ("58", None, None),
    ] + close_key)
    save_va = load_va + len(load)
    save = assemble(open_key + [
        ("6a 20 68 " + SLOTS + " 6a 03 6a 00 68 " + le32(value_va), None, None),  # REG_BINARY
        ("ff 74 24 14 ff 15 " + REG_SET_VALUE, None, None),
    ] + close_key)
    cast_va = save_va + len(save)
    cast = assemble([
        ("8b 4d bc 8b 89 ec 00 00 00", None, None),  # ecx = spellbook window
        ("83 79 60 ff 74 00", None, ("orig", "rel8")),  # a spell is selected:
        ("6a 09 eb 00", None, ("command", "rel8")),  # Command(9), cast it (as F5..F8 do)
        ("8b 4d b0 e8 00 00 00 00", "orig", (IS_SPELLBOOK_OPEN, "rel32")),
        ("85 c0 75 00", None, ("done", "rel8")),
        ("6a 05", None, None),                      # Command(5), open the book
        ("8b 4d b0 e8 00 00 00 00", "command", (MAP_COMMAND, "rel32")),
        ("b8 01 00 00 00", "done", None),
        ("e9 00 00 00 00", None, (MAP_KEY_HANDLED, "rel32")),
    ], cast_va)
    return REG_SUBKEY + REG_VALUE + load + save + cast, load_va, save_va, cast_va


def f1_f4_code(va):
    """Map key case for F1..F4: the F5..F8 code with slot = vk - 0x70 + 4."""
    return assemble([
        ("ff 35 " + CTRL_PRESSED, None, None),
        ("8b 45 08 83 e8 6c 50", None, None),       # slot
        ("68 17 04 00 00", None, None),             # spellbook->OnMessage(0x417, slot, ctrl)
        ("8b 4d bc 8b 89 ec 00 00 00", None, None),
        ("8b 11 ff 52 48", None, None),
        ("8b 4d b0 e8 00 00 00 00", None, (IS_SPELLBOOK_OPEN, "rel32")),
        ("85 c0 75 00", None, ("done", "rel8")),
        ("8b 45 08 83 e8 6c 50", None, None),
        ("8b 4d bc 8b 89 ec 00 00 00", None, None),
        ("e8 00 00 00 00", None, (SPELLBOOK_HAS_SPELL, "rel32")),
        ("85 c0 74 00", None, ("done", "rel8")),
        ("6a 09 8b 4d b0 e8 00 00 00 00", None, (MAP_COMMAND, "rel32")),  # cast
        ("e9 00 00 00 00", "done", (MAP_KEY_DONE, "rel32")),
    ], va)


# --- cursor ----------------------------------------------------------------------------------

# Every cursor change erases it from the primary surface and draws it again, while cnc-ddraw
# copies that surface to the screen from its own thread. A frame taken in between has no cursor
# or only a part of it, so a moving cursor looks see-through, a big item in hand most of all.
# The screen lock is made nestable and held over the whole change; with lock_surfaces=true in
# ddraw.ini the render thread waits for it.
SCREEN_LOCK, SCREEN_UNLOCK = 0x44C460, 0x44C4B0
SCREEN_LOCK_NESTED = (0x44C49E, "8b 44 24 00 59 c3 90 90 90 90 90 90",
                      "ff 05 fc 42 5e 00 8b 44 24 00 59 c3")  # inc [lock count], old exit
SCREEN_UNLOCK_NESTED = (0x44C4B1, "a1 fc 42 5e 00 85 c0 74 29",
                        "ff 0d fc 42 5e 00 75 2a 90")         # dec [lock count] / jnz exit
SCREEN_UNLOCK_COUNT = (0x44C4DA, "49", "90")                  # the old decrement after Unlock
CURSOR_HIDE, CURSOR_SHOW = 0x42A410, 0x42A430
# Alignment padding between the cursor methods, room for the new hide and show
CURSOR_HIDE_AREA, CURSOR_SHOW_AREA = (0x42A563, 0x42A570), (0x42A426, 0x42A430)
# (hide call, show call): set cursor, move, next animation frame, tooltip on, tooltip off,
# selection frame on, selection frame off
CURSOR_UPDATES = [
    (0x42A31B, 0x42A3F0), (0x42A62E, 0x42A678), (0x42A914, 0x42A91B),
    (0x42B495, 0x42B4F9), (0x42B8B4, 0x42B8EA), (0x42B11B, 0x42B129), (0x42B143, 0x42B151),
]


def cursor_hide_code(va):
    """Cursor hide that takes the screen lock first."""
    return assemble([
        ("51 e8 00 00 00 00", None, (SCREEN_LOCK, "rel32")),    # push ecx / lock
        ("59 e9 00 00 00 00", None, (CURSOR_HIDE, "rel32")),    # pop ecx / hide
    ], va)


def cursor_show_code(va):
    """Cursor show that releases the screen lock last."""
    return assemble([
        ("e8 00 00 00 00", None, (CURSOR_SHOW, "rel32")),
        ("e9 00 00 00 00", None, (SCREEN_UNLOCK, "rel32")),
    ], va)


def patch_cursor(img):
    for site, original, patched in (SCREEN_LOCK_NESTED, SCREEN_UNLOCK_NESTED, SCREEN_UNLOCK_COUNT):
        img.put(site, bytes.fromhex(original), bytes.fromhex(patched))
    hide_va, show_va = CURSOR_HIDE_AREA[0], CURSOR_SHOW_AREA[0]
    img.place(CURSOR_HIDE_AREA, cursor_hide_code(hide_va), fill_check=b"\x90")
    img.place(CURSOR_SHOW_AREA, cursor_show_code(show_va), fill_check=b"\x90")
    for hide_site, show_site in CURSOR_UPDATES:
        img.hook(b"\xe8", hide_site, hide_va, b"\xe8" + rel32(hide_site, CURSOR_HIDE))
        img.hook(b"\xe8", show_site, show_va, b"\xe8" + rel32(show_site, CURSOR_SHOW))


# --- build -----------------------------------------------------------------------------------

def build(source, width, height):
    if width < 1024 or height < 768 or width % 4:
        raise PatchError("ширина должна быть не меньше 1024 и кратна 4, высота не меньше 768")
    if hashlib.md5(source).hexdigest() != SOURCE_MD5:
        raise PatchError("этот ROM.EXE не поддерживается (нужна русская GOG-версия игры)")
    img = Image(source)

    patch_resolution(img, width, height)

    # sidebar and spellbook window code at the end of .text
    strip_va = CAVE[0]
    strip = stats_strip_code()
    panel_va = strip_va + len(strip)
    panel = panel_code()
    move_va = panel_va + len(panel)
    img.place(CAVE, strip + panel + window_move_code(move_va), fill_check=b"\0")
    img.hook(b"\xe8", STATS_STRIP_SITE[0], strip_va, bytes.fromhex(STATS_STRIP_SITE[1]))
    img.hook(b"\x52\xe8", PANEL_SITE[0], panel_va, bytes.fromhex(PANEL_SITE[1]))
    img.hook(b"\xe9", WINDOW_MOVE_SITE[0], move_va, bytes.fromhex(WINDOW_MOVE_SITE[1]))

    for va, original, patched in (MAP_ROWS_SITE, CURSOR_CLIP_SITE):
        img.put(va, bytes.fromhex(original), bytes.fromhex(patched))
    img.hook(b"\xe9", BAR_FILLS_SITE[0], BAR_FILLS_DONE, bytes.fromhex(BAR_FILLS_SITE[1]))
    for va in SPELLBOOK_OFFSET_SITES:
        img.put(va, bytes.fromhex(SPELLBOOK_OFFSET[0]), bytes.fromhex(SPELLBOOK_OFFSET[1]))

    # hotkeys: registry storage and "C" in DEAD2, slot table code and F1..F4 in DEAD1
    storage, load_va, save_va, cast_va = hotkey_storage_code(DEAD2[0])
    img.place(DEAD2, storage)
    img.hook(b"\xe9", CAST_KEY_SITE[0], cast_va, bytes.fromhex(CAST_KEY_SITE[1]))
    vas, va = {}, DEAD1[0]
    for name, code in slot_code({}, 0, 0).items():
        vas[name] = va
        va += len(code)
    f1_f4_va = va
    img.place(DEAD1, b"".join(slot_code(vas, load_va, save_va).values()) + f1_f4_code(f1_f4_va))
    for site, original, name in SLOT_SITES:
        img.hook(b"\xe8", site, vas[name], bytes.fromhex(original))
    img.put(MAP_KEY_CASE10[0], struct.pack("<I", MAP_KEY_CASE10[1]), struct.pack("<I", f1_f4_va))
    img.put(MAP_KEY_F1_F4_BYTES, b"\x0b" * 4, b"\x0a" * 4)
    for vk, (old, new) in MAIN_KEY_CASES.items():
        img.put(MAIN_KEY_BYTES + vk - 8, bytes([old]), bytes([new]))

    patch_cursor(img)

    # let the loader map the code areas and the slot table
    img.set_section_vsize(0, b".text", None, CAVE[1] - IMAGE_BASE - TEXT_RVA)
    index, name, data_rva_va, data_vsize = DATA_SECTION
    img.set_section_vsize(index, name, data_vsize, SLOTS_VA + 8 * 4 - data_rva_va)
    return bytes(img.data)


# --- command line ----------------------------------------------------------------------------

def default_game_dir():
    if getattr(sys, "frozen", False):  # PyInstaller executable
        return os.path.dirname(sys.executable)
    return os.getcwd()


def prompt(text):
    """input() that treats a closed or redirected stdin as an empty answer."""
    try:
        return input(text).strip()
    except EOFError:
        print()
        return ""


def ask_size():
    answer = prompt(f"Разрешение, например 1920x1080 [{DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]}]: ")
    if not answer:
        return DEFAULT_SIZE
    width, _, height = answer.lower().replace("х", "x").partition("x")  # Cyrillic "х" too
    return int(width), int(height)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Allods HD: создаёт ROM_HD.EXE из ROM.EXE.")
    parser.add_argument("width", type=int, nargs="?")
    parser.add_argument("height", type=int, nargs="?")
    parser.add_argument("--game-dir", default=default_game_dir(), help="папка с ROM.EXE (по умолчанию текущая)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    interactive = args.width is None and sys.stdin.isatty()

    try:
        if args.width is None:
            width, height = ask_size() if interactive else DEFAULT_SIZE
        elif args.height is None:
            raise PatchError("укажите и ширину, и высоту")
        else:
            width, height = args.width, args.height
        source_path = os.path.join(args.game_dir, SOURCE_NAME)
        if not os.path.isfile(source_path):
            raise PatchError(f"{SOURCE_NAME} не найден в {args.game_dir}")
        with open(source_path, "rb") as f:
            patched = build(f.read(), width, height)
        target_path = os.path.join(args.game_dir, TARGET_NAME)
        with open(target_path, "wb") as f:
            f.write(patched)
        print(f"Готово: {target_path} ({width}x{height})")
        status = 0
    except (PatchError, ValueError, OSError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        status = 1
    if interactive:  # keep the console window of a double-clicked exe open
        prompt("Нажмите Enter для выхода...")
    return status


if __name__ == "__main__":
    sys.exit(main())
