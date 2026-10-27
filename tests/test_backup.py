# SPDX-License-Identifier: GPL-2.0-or-later
# mypy: ignore-errors
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
# ruff: noqa: PLR2004
#
# This file is part of emorphed.

"""Preset backups: the read-only half of a restore point."""

import json
import os
import sys
import tempfile

import pytest

from emorphed import cli
from emorphed.demo import DemoDevice
from emu import backup as bk
from emu import messages as m
from emu.favorites import data_dir
from vinsynlib import backup as vbk

INDEX = 0


class TestTheEnvelope:
    def test_a_real_preset_round_trips(self, tmp_path) -> None:
        device = DemoDevice()
        words = device.read_preset(INDEX)
        record = bk.save_preset(
            words,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        assert record.kind == bk.KIND
        assert record.slot == str(INDEX)
        assert record.name == m.decode_name(words[: m.NAME_CHARS]).rstrip()
        assert record.error is None

        loaded = bk.load(record.id, directory=str(tmp_path))
        assert list(loaded.words) == list(words)
        assert loaded == m.to_words(words)

    def test_the_envelope_never_overwrites(self, tmp_path) -> None:
        device = DemoDevice()
        words = device.read_preset(INDEX)
        first = bk.save_preset(
            words,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        second = bk.save_preset(
            words,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        assert first.id != second.id
        assert os.path.isfile(os.path.join(str(tmp_path), first.id))
        assert os.path.isfile(os.path.join(str(tmp_path), second.id))
        assert len(bk.list_backups(str(tmp_path))) == 2

    def test_the_default_directory_is_under_the_data_directory(
        self, monkeypatch, tmp_path
    ) -> None:
        # data_dir() is per-platform: XDG_DATA_HOME only steers it on
        # Linux/BSD. Point the platform's own variable at tmp_path so the
        # test means the same thing everywhere CI runs it.
        if sys.platform == "win32":
            monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        elif sys.platform == "darwin":
            monkeypatch.setenv("HOME", str(tmp_path))
        else:
            monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert bk.default_dir() == os.path.join(data_dir(), "backups")
        assert bk.default_dir().startswith(str(tmp_path))
        assert os.path.basename(bk.default_dir()) == "backups"
        assert "emorphed" in bk.default_dir()

    def test_list_is_lenient_about_a_corrupt_file(self, tmp_path) -> None:
        device = DemoDevice()
        bk.save_preset(
            device.read_preset(INDEX),
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        (tmp_path / "corrupt.json").write_text("not json", encoding="utf-8")
        rows = bk.list_backups(str(tmp_path))
        good = [row for row in rows if row.error is None]
        broken = [row for row in rows if row.error is not None]
        assert len(good) == 1
        assert len(broken) == 1
        assert broken[0].id == "corrupt.json"
        assert "Expecting" in (broken[0].error or "")

    def test_a_directory_that_is_not_there_lists_nothing(
        self, tmp_path
    ) -> None:
        assert bk.list_backups(str(tmp_path / "nope")) == []

    def test_listing_skips_something_that_is_not_a_file(
        self, tmp_path
    ) -> None:
        (tmp_path / "a-directory").mkdir()
        assert bk.list_backups(str(tmp_path)) == []

    def test_a_backup_can_be_named_by_its_full_path(self, tmp_path) -> None:
        device = DemoDevice()
        record = bk.save_preset(
            device.read_preset(INDEX),
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        full = os.path.join(str(tmp_path), record.id)
        loaded = bk.load(full)
        assert list(loaded.words) == list(device.read_preset(INDEX))

    def test_load_refuses_a_preset_block_that_is_not_bytes(
        self, tmp_path
    ) -> None:
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND,
            slot=str(INDEX),
            name="Junk",
            device_id="0",
            source="test",
            blocks={bk.BLOCK: b""},
        )
        with pytest.raises(ValueError, match="no preset block"):
            bk.load(os.path.basename(path), directory=str(tmp_path))

    def test_load_refuses_a_backup_that_is_not_a_preset(
        self, tmp_path
    ) -> None:
        path = vbk.save(
            str(tmp_path),
            kind="patch",
            slot="01",
            name="Not A Preset",
            device_id="0",
            source="test",
            blocks={"patch": b"\xf0\xf7"},
        )
        with pytest.raises(ValueError, match="not a preset backup"):
            bk.load(os.path.basename(path), directory=str(tmp_path))

    def test_load_refuses_a_preset_with_no_block(self, tmp_path) -> None:
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND,
            slot=str(INDEX),
            name="Empty",
            device_id="0",
            source="test",
            blocks={},
        )
        with pytest.raises(ValueError, match="no preset block"):
            bk.load(os.path.basename(path), directory=str(tmp_path))


class TestTheMidimapEnvelope:
    def test_a_real_midimap_round_trips(self, tmp_path) -> None:
        device = DemoDevice()
        words = list(range(360))
        device.send_midimap(0, words)
        stored = device.read_midimap(0)
        record = bk.save_midimap(
            stored,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        assert record.kind == bk.KIND_MIDIMAP
        assert record.slot == str(INDEX)
        assert record.error is None

        loaded = bk.load_midimap(record.id, directory=str(tmp_path))
        assert list(loaded.words) == list(stored)
        assert loaded == m.to_words(stored)
        assert isinstance(loaded, bk.MidimapBytes)

    def test_the_envelope_never_overwrites(self, tmp_path) -> None:
        device = DemoDevice()
        words = list(range(360))
        device.send_midimap(0, words)
        stored = device.read_midimap(0)
        first = bk.save_midimap(
            stored,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        second = bk.save_midimap(
            stored,
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        assert first.id != second.id
        assert os.path.isfile(os.path.join(str(tmp_path), first.id))
        assert os.path.isfile(os.path.join(str(tmp_path), second.id))
        assert len(bk.list_backups(str(tmp_path))) == 2

    def test_load_with_kind_midimap_returns_midimap_bytes(
        self, tmp_path
    ) -> None:
        device = DemoDevice()
        words = list(range(360))
        device.send_midimap(0, words)
        record = bk.save_midimap(
            device.read_midimap(0),
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        loaded = bk.load(record.id, directory=str(tmp_path), kind="midimap")
        assert isinstance(loaded, bk.MidimapBytes)

    def test_load_refuses_a_preset_asked_for_as_midimap(
        self, tmp_path
    ) -> None:
        device = DemoDevice()
        record = bk.save_preset(
            device.read_preset(INDEX),
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        with pytest.raises(ValueError, match="not a midimap backup"):
            bk.load(record.id, directory=str(tmp_path), kind="midimap")

    def test_load_midimap_refuses_a_preset_kind(self, tmp_path) -> None:
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND,
            slot=str(INDEX),
            name="Not A Midimap",
            device_id="0",
            source="test",
            blocks={bk.BLOCK: b"\xf0\xf7"},
        )
        with pytest.raises(ValueError, match="not a midimap backup"):
            bk.load_midimap(os.path.basename(path), directory=str(tmp_path))

    def test_load_midimap_refuses_an_empty_block(self, tmp_path) -> None:
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND_MIDIMAP,
            slot=str(INDEX),
            name="Empty",
            device_id="0",
            source="test",
            blocks={},
        )
        with pytest.raises(ValueError, match="no midimap block"):
            bk.load_midimap(os.path.basename(path), directory=str(tmp_path))


class TestTheCliBackupCommands:
    def test_list_needs_no_unit(self, monkeypatch, capsys, tmp_path) -> None:
        def explode(*args, **kwargs):
            raise AssertionError("backup list tried to open a port")

        monkeypatch.setattr(
            "emu.bridge.MorpheusBridge.open", explode, raising=False
        )
        monkeypatch.setattr(
            "emu.bridge.MorpheusBridge.connect", explode, raising=False
        )
        monkeypatch.setattr("emorphed.demo.DemoDevice", explode, raising=False)
        assert cli.main(["backup", "list", "--dir", str(tmp_path)]) == 0
        assert f"no backups in {tmp_path}" in capsys.readouterr().out

    def test_list_reports_a_corrupt_file_rather_than_dropping_it(
        self, capsys, tmp_path
    ) -> None:
        (tmp_path / "corrupt.json").write_text("not json", encoding="utf-8")
        assert cli.main(["backup", "list", "--dir", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "corrupt.json" in out
        assert "Expecting" in out

    def test_list_json_is_one_object(self, capsys, tmp_path) -> None:
        # save one preset via the library to avoid a full-region round trip
        device = DemoDevice()
        bk.save_preset(
            device.read_preset(INDEX),
            device_id=device.device_id,
            slot=INDEX,
            directory=str(tmp_path),
        )
        assert (
            cli.main(["backup", "list", "--dir", str(tmp_path), "--json"]) == 0
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["directory"] == str(tmp_path)
        assert len(payload["backups"]) == 1
        assert payload["backups"][0]["kind"] == "preset"
        assert payload["backups"][0]["error"] is None


def test_the_demo_device_id_is_the_one_the_backup_records() -> None:
    device = DemoDevice()
    record = bk.save_preset(
        device.read_preset(INDEX),
        device_id=device.device_id,
        slot=INDEX,
        directory=tempfile.mkdtemp(),
    )
    assert record.device_id == str(device.device_id)
