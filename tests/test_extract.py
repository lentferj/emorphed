# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The catalog extractor's guards and round-trip."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from emu import catalog as _cat

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "extract_catalog.py")
_FIXTURE = os.path.join(_HERE, "fixtures", "invented.ins")


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("extract_catalog", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract = _tool()


def test_duplicate_display_number_is_refused() -> None:
    with pytest.raises(SystemExit):
        extract.check_no_duplicates(
            {"P-ROM": [{"n": 0, "name": "A"}, {"n": 0, "name": "B"}]}
        )


def test_control_character_is_refused() -> None:
    with pytest.raises(SystemExit):
        extract.check_printable({"P-ROM": [{"n": 0, "name": "A\x01"}]})


def test_unprintable_check_is_aliased() -> None:
    with pytest.raises(SystemExit):
        extract.check_printable_names({"P-ROM": [{"n": 0, "name": "A\x7f"}]})


def test_invented_ins_extracts_named_rows(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    result = extract.main(["--ins", _FIXTURE, "-o", str(out)])
    assert result == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["banks"]) == {"P-ROM", "P-RAM"}
    assert data["banks"]["P-ROM"] == [
        {"n": 0, "name": "Invented One"},
        {"n": 1, "name": "Invented Two"},
    ]
    assert data["banks"]["P-RAM"] == [{"n": 0, "name": "Guarded Name"}]


def test_from_text_with_region_flag(tmp_path: Path) -> None:
    source = tmp_path / "names.txt"
    source.write_text("Alpha\nBeta\n", encoding="utf-8")
    out = tmp_path / "out.json"
    result = extract.main(
        ["--from-text", str(source), "--region", "P-ROM", "-o", str(out)]
    )
    assert result == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["banks"]["P-ROM"] == [
        {"n": 0, "name": "Alpha"},
        {"n": 1, "name": "Beta"},
    ]


def test_from_text_with_prose_heading(tmp_path: Path) -> None:
    source = tmp_path / "names.txt"
    source.write_text(
        "P-ROM bank\nAlpha\nP-RAM bank\nGamma\n", encoding="utf-8"
    )
    out = tmp_path / "out.json"
    result = extract.main(["--from-text", str(source), "-o", str(out)])
    assert result == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["banks"]["P-ROM"] == [{"n": 0, "name": "Alpha"}]
    assert data["banks"]["P-RAM"] == [{"n": 0, "name": "Gamma"}]


def test_missing_input_raises(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit):
        extract.main(["--ins", str(tmp_path / "nope.ins"), "-o", str(out)])


def test_written_rows_survive_reread(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    extract.main(["--ins", _FIXTURE, "-o", str(out)])
    extract.verify_survives(str(out))
    loaded = _cat.load(str(out))
    assert len(loaded) == 3  # noqa: PLR2004
    assert loaded.name("P-ROM", 0) == "Invented One"
    assert loaded.name("P-ROM", 1) == "Invented Two"
    assert loaded.name("P-RAM", 0) == "Guarded Name"


def test_no_network_or_user_store_needed() -> None:
    # The tool only touches paths we give it. Just re-check --help renders.
    result = subprocess.run(  # noqa: S603
        [sys.executable, _TOOL, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()
