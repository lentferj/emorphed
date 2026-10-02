# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The wire protocol is transcribed as data from E-mu's own MIDI
# Specification, printed in full as pages 225-250 of the Morpheus
# Operation Manual (E-mu Systems, 1993), and checked against 2176 preset
# dumps the instrument produced. The transport layer is ported from the
# sibling p2ked, x5ded, kwsed, rxved and nanosyned projects.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)

"""The wire format and the memory map. Every fixture is invented."""

import pytest

from emu import banks
from emu import dumps
from emu import messages as m


class TestFourteenBitWords:
    """Every value in a dump is two MIDI bytes, lsb first."""

    def test_words_round_trip(self) -> None:
        values = [0, 1, 127, 128, 8191, 16383]
        assert m.from_words(m.to_words(values)) == values

    def test_the_low_seven_bits_go_first(self) -> None:
        assert list(m.to_words([0x3FFF])) == [0x7F, 0x7F]
        assert list(m.to_words([0x0001])) == [0x01, 0x00]
        assert list(m.to_words([0x0080])) == [0x00, 0x01]

    def test_a_byte_with_bit_7_set_is_refused(self) -> None:
        with pytest.raises(m.ProtocolError, match="bit 7"):
            m.from_words(bytes([0x00, 0x80]))

    def test_values_are_signed_to_bit_13(self) -> None:
        """A pan of -7 read as unsigned is 16377, which a screen will
        happily show."""
        assert m.signed(0x3FF9) == -7
        assert m.signed(0x2000) == -8192
        assert m.signed(0x1FFF) == 8191
        assert m.signed(0) == 0

    def test_a_trailing_odd_byte_is_dropped(self) -> None:
        assert m.from_words(bytes([0x01, 0x00, 0x7F])) == [1]


class TestNames:
    def test_a_name_is_twelve_words(self) -> None:
        words = m.encode_name("Invented")
        assert len(words) == m.NAME_CHARS
        assert m.decode_name(words) == "Invented    "

    def test_it_is_truncated_not_wrapped(self) -> None:
        assert (
            m.decode_name(m.encode_name("A very long name indeed"))
            == "A very long "
        )

    def test_the_character_set_has_an_edge(self) -> None:
        with pytest.raises(m.ProtocolError, match="ASCII 32-127"):
            m.encode_name("\t")

    def test_a_short_record_is_refused(self) -> None:
        with pytest.raises(m.ProtocolError, match="12 words"):
            m.decode_name([65, 66])


class TestFraming:
    def test_a_message_carries_the_emu_header(self) -> None:
        framed = m.frame(m.Command.VERSION_REQUEST, device=3)
        assert list(framed) == [
            0xF0,
            m.EMU_ID,
            m.MORPHEUS_ID,
            3,
            m.Command.VERSION_REQUEST,
            0xF7,
        ]

    def test_the_device_id_is_four_bits(self) -> None:
        with pytest.raises(m.ProtocolError, match="0-15"):
            m.frame(m.Command.VERSION_REQUEST, device=16)

    def test_a_foreign_message_parses_as_none(self) -> None:
        assert m.parse(bytes([0xF0, 0x43, 0x00, 0xF7])) is None

    def test_a_proteus_id_message_is_accepted(self) -> None:
        """The Morpheus answers to 04 as well as 0C, so a reader that
        rejected it would miss data the instrument itself would take."""
        raw = m.frame(m.Command.VERSION_DATA, [1], product=m.PROTEUS_ID)
        packet = m.parse(raw)
        assert packet is not None
        assert packet.command == m.Command.VERSION_DATA

    def test_a_request_is_never_mistaken_for_its_reply(self) -> None:
        echo = m.parse(m.preset_request(5))
        assert echo is not None
        assert echo.command == m.Command.PRESET_REQUEST
        assert m.Command.REPLY_TO[echo.command] == m.Command.PRESET_DATA

    def test_a_bank_request_is_the_base_plus_the_bank(self) -> None:
        raw = m.preset_bank_request(2)
        packet = m.parse(raw)
        assert packet is not None
        number = packet.body[0] | (packet.body[1] << 7)
        assert number == m.BANK_REQUEST_BASE + 2


def _preset_dump(number: int, name: str, device: int = 0) -> bytes:
    words = m.encode_name(name) + [0] * (278 - m.NAME_CHARS)
    body = m.to_words(words)
    head = [1, number & 0x7F, (number >> 7) & 0x7F]
    return bytes(
        [
            0xF0,
            m.EMU_ID,
            m.MORPHEUS_ID,
            device,
            m.Command.PRESET_DATA,
            *head,
            *body,
            m.checksum(body),
            0xF7,
        ]
    )


class TestChecksum:
    def test_it_is_the_seven_bit_sum_of_the_data(self) -> None:
        """Measured across 2176 real dumps; the manual only says "cs"."""
        body = bytes([0x7F, 0x7F, 0x02])
        assert m.checksum(body) == (0x7F + 0x7F + 0x02) & 0x7F

    def test_a_good_dump_is_kept(self) -> None:
        library = dumps.read_bytes(_preset_dump(0, "Invented"))
        assert library.names()[0] == "Invented    "
        assert not library.corrupt

    def test_a_damaged_dump_is_reported_not_dropped(self) -> None:
        raw = bytearray(_preset_dump(0, "Invented"))
        raw[-2] ^= 0x01
        library = dumps.read_bytes(bytes(raw))
        assert library.corrupt and "checksum" in library.corrupt[0]
        assert not library.presets

    def test_the_right_length_is_also_required(self) -> None:
        raw = _preset_dump(0, "Invented")
        assert len(raw) == m.PRESET_DATA_BYTES


class TestTheMemoryMap:
    def test_presets_are_three_banks_of_128(self) -> None:
        """The manual's Preset Request says card is 256-319, and four
        lines later that banks are 0-2 of 128 each. Real dumps hold
        0-383. Two against one."""
        assert banks.TOTAL_PRESETS == 384
        assert banks.TOTAL_PRESETS == 3 * banks.PRESETS_PER_BANK

    def test_an_index_is_not_a_number(self) -> None:
        item = banks.slot("P-ROM", 5)
        assert item.number == 5
        assert item.index == 133

    def test_a_bank_is_worked_out_from_the_index(self) -> None:
        assert (
            banks.bank_of(banks.Kind.PRESET, banks.slot("P-ROM", 0).index) == 1
        )
        assert (
            banks.bank_of(banks.Kind.PRESET, banks.slot("P-CARD", 0).index)
            == 2
        )

    def test_card_regions_are_marked(self) -> None:
        assert banks.region("P-CARD").needs_card
        assert not banks.region("P-RAM").needs_card

    def test_only_ram_is_writable(self) -> None:
        writable = {r.id for r in banks.regions() if r.writable}
        assert writable == {"P-RAM", "H-RAM", "M-RAM"}


class TestSelecting:
    def test_controller_32_carries_the_bank(self) -> None:
        """The manual's own sequence: Bn 00 00 20 bb Cn pp."""
        out = banks.select_messages(banks.slot("P-ROM", 5), channel=2)
        assert [list(x) for x in out] == [
            [0xB2, 0x00, 0x00],
            [0xB2, 0x20, 1],
            [0xC2, 5],
        ]

    def test_controller_zero_is_sent_and_is_zero(self) -> None:
        out = banks.select_messages(banks.slot("P-CARD", 0))
        assert list(out[0]) == [0xB0, 0x00, 0x00]

    def test_a_midimap_has_no_program_change(self) -> None:
        with pytest.raises(LookupError, match="not selected with a program"):
            banks.select_messages(banks.slot("M-RAM", 0))

    def test_the_channel_lands_in_every_status_byte(self) -> None:
        out = banks.select_messages(banks.slot("P-RAM", 1), channel=9)
        assert all((x[0] & 0x0F) == 9 for x in out)


class TestNameLists:
    def test_a_list_reply_is_unpacked(self) -> None:
        names = ["Invented One", "Invented Two"]
        body = bytearray([len(names) & 0x7F, (len(names) >> 7) & 0x7F])
        for name in names:
            body += bytes(ord(c) for c in name)
            body.append(0)
        packet = m.Packet(
            0, m.Command.PRESET_LIST_DATA, None, None, bytes(body)
        )
        assert m.parse_name_list(packet) == names

    def test_a_short_reply_gives_what_arrived(self) -> None:
        """A list cut off partway is still worth showing."""
        body = bytearray([10, 0]) + bytes(ord(c) for c in "Invented One")
        packet = m.Packet(
            0, m.Command.PRESET_LIST_DATA, None, None, bytes(body)
        )
        assert m.parse_name_list(packet) == ["Invented One"]
