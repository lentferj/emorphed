#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors

"""Capture README screenshots for emorphed.

Drives the Textual app headlessly via run_test, exports SVG via
App.export_screenshot, converts to PNG with cairosvg at 820 px width.

Rules this script obeys (see README "Screenshots" and CLAUDE.md):

- DemoDevice only: no hardware, no MIDI ports, nothing sent. The general
  browser reads names off the demo; every name shown is invented.
- One fresh app per shot: every shot starts from launch state, so a modal
  left open by one shot can never leak into the next.
- SVG fixups: DejaVu Sans Mono (covers every UI glyph), the remote
  @font-face blocks removed (no network at capture time), and Rich's macOS
  window chrome (traffic lights + title) stripped so the shot reads as a
  plain terminal capture.
- Temp config and a temp favourites database per shot: nothing is written
  to the user's data directory.
"""

from __future__ import annotations

import asyncio
import html
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from cairosvg import svg2png  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover - environment check
    raise SystemExit(
        "cairosvg is required to render screenshots; install it with "
        "`.venv/bin/python -m pip install cairosvg`."
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from emorphed.app import EmorphedApp  # noqa: E402
from emorphed.demo import DemoDevice  # noqa: E402
from emorphed.scan import SCAN_OFFER, ScanOfferScreen  # noqa: E402
from emu import catalog as cat  # noqa: E402
from emu.favorites import Favorites  # noqa: E402
from vinsynlib.ui.hints import KeyHints  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "screenshots"
SCREEN_W = 820
BROWSER_SIZE = (132, 42)
MODAL_SIZE = (120, 36)
SCAN_OFFER_SIZE = (150, 30)

MARKERS: dict[str, list[str]] = {
    "general": ["Qrk:PewterGu", "index"],
    "kind-hyper": ["hyperpreset"],
    "kind-midimap": ["midimap"],
    "favourites-bank": ["favourite"],
    "favourites-all": ["favourite"],
    "rating-filter": ["rating"],
    "search": ["Search"],
    "device": ["device ID"],
    "help": ["What the Morpheus holds"],
    "scan-offer": ["no name catalog"],
}


def fix_svg(svg: str) -> str:
    """Terminal font, no remote fonts, no window chrome."""
    svg = svg.replace(
        "font-family: Fira Code, monospace",
        'font-family: "DejaVu Sans Mono", monospace',
    )
    svg = re.sub(r"@font-face\s*\{[^}]+\}", "", svg)
    svg = re.sub(r"<circle[^>]*/>", "", svg)
    svg = re.sub(r"<circle[^>]*>.*?</circle>", "", svg)
    svg = re.sub(r'<text[^>]*class="[^"]*-title"[^>]*>.*?</text>', "", svg)
    return svg


def screen_text(svg: str) -> str:
    """The visible text of a shot, for the run transcript."""
    text = re.sub(r"<style.*?</style>", "", svg, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines)


async def capture(app: Any, pilot: Any, name: str) -> str:
    """Pin hint heights, export, fix, write SVG+PNG. Returns the SVG."""
    await pilot.pause()
    for h in app.query(KeyHints):
        rendered = h.render()
        if rendered:
            h.styles.height = str(str(rendered).count("\n") + 1)
    await pilot.pause()

    svg = fix_svg(app.export_screenshot())
    (OUT_DIR / f"{name}.svg").write_text(svg, encoding="utf-8")
    out_png = OUT_DIR / f"{name}.png"
    svg2png(
        bytestring=svg.encode(),
        write_to=str(out_png),
        output_width=SCREEN_W,
    )
    print(f"  {name}.png ({out_png.stat().st_size // 1024} KB)")
    return svg


def check(name: str, svg: str) -> None:
    text = screen_text(svg).lower()
    wants = MARKERS[name]
    if not any(w.lower() in text for w in wants):
        raise AssertionError(
            f"{name}: none of {wants} in shot text:\n{text[:800]}"
        )
    print(f"  markers ok: {wants}")


def make_app(
    tmp: Path, *, demo: bool = True, offer_scan: bool = False
) -> EmorphedApp:
    (tmp / "config").mkdir(exist_ok=True)
    (tmp / "fav").mkdir(exist_ok=True)
    return EmorphedApp(
        DemoDevice(),
        catalog=cat.empty(),
        favorites=Favorites(str(tmp / "fav" / "favorites.db")),
        config_path=str(tmp / "config" / "config.toml"),
        demo=demo,
        offer_scan=offer_scan,
    )


async def wait_for_text(
    app: Any, pilot: Any, marker: str, tries: int = 200
) -> None:
    for _ in range(tries):
        if marker.lower() in screen_text(app.export_screenshot()).lower():
            return
        await pilot.pause()
    raise AssertionError(f"never saw {marker!r} on screen")


async def wait_for_screen(
    app: Any, pilot: Any, cls: type, tries: int = 200
) -> None:
    for _ in range(tries):
        if isinstance(app.screen, cls):
            return
        await pilot.pause()
    raise AssertionError(
        f"top screen is {type(app.screen).__name__}, not {cls.__name__}"
    )


async def wait_for_idle(app: Any, pilot: Any, tries: int = 200) -> None:
    for _ in range(tries):
        if not app._busy:
            return
        await pilot.pause()
    raise AssertionError("wire stayed busy")


# --- shots ---------------------------------------------------------------


async def shot_general(app: Any, pilot: Any) -> str:
    await wait_for_idle(app, pilot)
    await pilot.press("r")
    await wait_for_text(app, pilot, "Qrk:PewterGu")
    return await capture(app, pilot, "general")


async def shot_kind_hyper(app: Any, pilot: Any) -> str:
    await pilot.press("k")
    await pilot.pause()
    await wait_for_idle(app, pilot)
    await pilot.press("r")
    await wait_for_text(app, pilot, "hyperpreset")
    return await capture(app, pilot, "kind-hyper")


async def shot_kind_midimap(app: Any, pilot: Any) -> str:
    await pilot.press("k")
    await pilot.pause()
    await pilot.press("k")
    await pilot.pause()
    await wait_for_idle(app, pilot)
    await pilot.press("r")
    await wait_for_text(app, pilot, "midimap")
    return await capture(app, pilot, "kind-midimap")


async def shot_favourites_bank(app: Any, pilot: Any) -> str:
    await pilot.press("f")
    await pilot.pause()
    await pilot.press("down")
    await pilot.press("f")
    await pilot.pause()
    await pilot.press("F")
    await pilot.pause()
    return await capture(app, pilot, "favourites-bank")


async def shot_favourites_all(app: Any, pilot: Any) -> str:
    for _ in range(4):
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
    await pilot.press("F")
    await pilot.pause()
    await pilot.press("F")
    await pilot.pause()
    return await capture(app, pilot, "favourites-all")


async def shot_rating_filter(app: Any, pilot: Any) -> str:
    await pilot.press("V")
    await wait_for_text(app, pilot, "rating")
    return await capture(app, pilot, "rating-filter")


async def shot_search(app: Any, pilot: Any) -> str:
    await pilot.press("/")
    await wait_for_text(app, pilot, "Search")
    return await capture(app, pilot, "search")


async def shot_device(app: Any, pilot: Any) -> str:
    await wait_for_idle(app, pilot)
    await pilot.press("i")
    await wait_for_text(app, pilot, "device ID")
    return await capture(app, pilot, "device")


async def shot_help(app: Any, pilot: Any) -> str:
    await pilot.press("?")
    await wait_for_text(app, pilot, "What the Morpheus holds")
    return await capture(app, pilot, "help")


async def shot_scan_offer(app: Any, pilot: Any) -> str:
    await wait_for_screen(app, pilot, ScanOfferScreen)
    svg = await capture(app, pilot, "scan-offer")
    rendered = screen_text(svg)
    # Every WORD of the offer must be on screen, whole. The dialog overlays
    # the browser, so the SVG's text carries the pane borders between the
    # dialog's lines and Textual re-wraps to the dialog's own width: neither
    # a whole-text nor a line-by-line compare can work here. A word that was
    # clipped at the edge would come through partial (the bug this guard
    # exists for: "one request per k"), so whole-word presence is the test.
    box = (
        "\u2502\u2500\u250c\u2510\u2514\u2518"
        "\u251c\u2524\u252c\u2534\u253c"
        "\u256d\u256e\u2570\u256f\u2576\u2574"
    )
    plain = "".join(" " if ch in box else ch for ch in rendered)
    rendered_words = set(" ".join(plain.split()).split())
    missing = [
        word
        for word in " ".join(SCAN_OFFER.split()).split()
        if word not in rendered_words
    ]
    if missing:
        raise AssertionError(
            f"scan-offer: {len(missing)} word(s) of the offer are not on "
            f"screen, whole: {missing[:6]}"
        )
    # What must fit is the DIALOG, not the screen: the offer is a modal over
    # the browser now, and the backdrop legitimately fills the frame. The
    # dialog's inner width is its CSS (width 72, padding 1 2, solid border).
    dialog_inner = 72 - 4 - 2
    longest = max((len(line) for line in SCAN_OFFER.splitlines()), default=0)
    if longest > dialog_inner:
        raise AssertionError(
            f"scan-offer: the offer's longest line is {longest} characters, "
            f"wider than the dialog's {dialog_inner} -- it would re-wrap"
        )
    return svg


SHOTS: list[tuple[str, Any, tuple[int, int], bool, bool]] = [
    ("general", shot_general, BROWSER_SIZE, True, False),
    ("kind-hyper", shot_kind_hyper, BROWSER_SIZE, True, False),
    ("kind-midimap", shot_kind_midimap, BROWSER_SIZE, True, False),
    ("favourites-bank", shot_favourites_bank, BROWSER_SIZE, True, False),
    ("favourites-all", shot_favourites_all, BROWSER_SIZE, True, False),
    ("rating-filter", shot_rating_filter, MODAL_SIZE, True, False),
    ("search", shot_search, MODAL_SIZE, True, False),
    ("device", shot_device, MODAL_SIZE, True, False),
    ("help", shot_help, MODAL_SIZE, True, False),
    ("scan-offer", shot_scan_offer, SCAN_OFFER_SIZE, False, True),
]


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for name, fn, size, demo, offer_scan in SHOTS:
            sub = tmp / name
            sub.mkdir(exist_ok=True)
            app = make_app(sub, demo=demo, offer_scan=offer_scan)
            async with app.run_test(size=size) as pilot:
                svg = await fn(app, pilot)
            check(name, svg)
            print(f"--- {name} ---")
            print(screen_text(svg)[:900])
            print()
    print(f"Done. Screenshots in {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
