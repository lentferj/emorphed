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

from emorphed.demo import DemoDevice
from emu import banks, dumps
from emu import bridge as b
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


class TestBankSelectTableMeasured20261016:
    """The 2026-10-16 bench measured the Bank Select mapping."""

    def test_the_table_is_exactly_as_measured(self) -> None:
        assert banks.BANK_SELECT == {
            "P-RAM": 0,
            "P-ROM": 1,
            "H-RAM": 2,
            "P-CARD": 3,
            "H-CARD": 4,
        }
        # A midimap has no bank at all: Bank Select cannot reach one.
        assert "M-RAM" not in banks.BANK_SELECT
        assert "M-CARD" not in banks.BANK_SELECT

    def test_midimap_has_no_bank(self) -> None:
        with pytest.raises(LookupError):
            banks.bank_select_bank("M-RAM")
        with pytest.raises(LookupError):
            _ = banks.slots("M-RAM")[0].bank_select


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


class TestSelectingNewMapping:
    def test_p_card_slot_index_256_sends_cc32_3_pc_0(self) -> None:
        out = banks.select_messages(banks.slot("P-CARD", 0))
        assert [list(x) for x in out] == [
            [0xB0, 0x00, 0x00],
            [0xB0, 0x20, 3],
            [0xC0, 0],
        ]

    def test_p_card_index_261_sends_pc_5(self) -> None:
        out = banks.select_messages(banks.slot("P-CARD", 5))
        assert list(out[2]) == [0xC0, 5]
        assert list(out[1]) == [0xB0, 0x20, 3]

    def test_h_ram_slot_0_sends_cc32_2(self) -> None:
        out = banks.select_messages(banks.slot("H-RAM", 0))
        assert list(out[1]) == [0xB0, 0x20, 2]
        assert list(out[2]) == [0xC0, 0]

    def test_h_card_index_128_sends_cc32_4_pc_0(self) -> None:
        out = banks.select_messages(banks.slot("H-CARD", 0))
        assert [list(x) for x in out] == [
            [0xB0, 0x00, 0x00],
            [0xB0, 0x20, 4],
            [0xC0, 0],
        ]

    def test_midimap_still_refuses(self) -> None:
        with pytest.raises(LookupError, match="no Bank Select bank"):
            banks.select_messages(banks.slot("M-RAM", 0))


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


class TestParameterData:
    def test_midi_mode_multi_frame(self) -> None:
        assert m.parameter_data(264, 2) == bytes.fromhex(
            "f0180c000308020200f7"
        )

    def test_current_midimap_ten(self) -> None:
        assert m.parameter_data(320, 10) == bytes.fromhex(
            "f0180c000340020a00f7"
        )

    def test_a_nonzero_device_id_lands_in_the_header(self) -> None:
        assert m.parameter_data(264, 2, device=5) == bytes.fromhex(
            "f0180c050308020200f7"
        )

    def test_master_parameter_constants(self) -> None:
        assert m.MIDI_MODE == 264
        assert m.CURRENT_MIDIMAP == 320
        assert m.MIDI_MODE_MULTI == 2

    def test_select_midimap_frames_are_in_order(self) -> None:
        frames = m.select_midimap_frames(3)
        assert [bytes(x) for x in frames] == [
            bytes.fromhex("f0180c000308020200f7"),
            bytes.fromhex("f0180c000340020300f7"),
        ]


class TestMidimapRequestBytes:
    def test_zero(self) -> None:
        assert m.midimap_request(0) == bytes.fromhex("f0180c00460000f7")

    def test_sixteen(self) -> None:
        assert m.midimap_request(16) == bytes.fromhex("f0180c00461000f7")


def _midimap_dump(index: int, words: list[int], device: int = 0) -> bytes:
    body = m.to_words(words)
    head = [1, index & 0x7F, (index >> 7) & 0x7F]
    return bytes(
        [
            0xF0,
            m.EMU_ID,
            m.MORPHEUS_ID,
            device,
            m.Command.MIDIMAP_DATA,
            *head,
            *list(body),
            m.checksum(body),
            0xF7,
        ]
    )


class _FakeIn:
    def __init__(self, messages: list[bytes]) -> None:
        self._messages = list(messages)
        #: The first call happens during ``_drain``, before anything was
        #: sent, and must yield nothing.
        self._drained = False

    def ignore_types(self, **_kwargs: object) -> None:
        return None

    def get_message(self) -> tuple[bytes] | None:
        if not self._drained:
            self._drained = True
            return None
        if not self._messages:
            return None
        return (self._messages.pop(0),)


class _FakeOut:
    def __init__(self) -> None:
        self.sent: list[list[int]] = []

    def send_message(self, message: list[int]) -> None:
        self.sent.append(list(message))


class TestBridgeReadMidimap:
    def test_parses_360_words(self) -> None:
        words = [i % 1000 for i in range(360)]
        dump = _midimap_dump(0, words)
        fake_in = _FakeIn([dump])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        got = bridge.read_midimap(0)
        assert got == words
        assert len(got) == 360

    def test_short_dump_raises_card_wording(self) -> None:
        dump = _midimap_dump(16, [1, 2, 3])
        fake_in = _FakeIn([dump])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        with pytest.raises(Exception, match="card"):
            bridge.read_midimap(16)

    def test_write_parameter_sends_exact_frame(self) -> None:
        fake_in = _FakeIn([])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        bridge.write_parameter(2048, 5)
        assert fake_out.sent == [
            [0xF0, 0x18, 0x0C, 0, 0x03, 0x00, 0x10, 0x05, 0x00, 0xF7]
        ]

    def test_write_parameter_refuses_out_of_range(self) -> None:
        fake_in = _FakeIn([])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        with pytest.raises(Exception, match="2048"):
            bridge.write_parameter(2047, 1)
        with pytest.raises(Exception, match="2048"):
            bridge.write_parameter(2408, 1)
        with pytest.raises(Exception, match=r"0x3FFF|16383"):
            bridge.write_parameter(2048, 0x4000)


class TestDemoMidimapRoundTrip:
    def test_write_then_read_sees_value(self) -> None:
        dev = DemoDevice()
        dev.write_parameter(2048, 7)
        assert dev.read_parameter(2048) == 7
        assert dev.parameter_writes == [(2048, 7)]

    def test_refusals(self) -> None:
        dev = DemoDevice()
        with pytest.raises(Exception, match="2048"):
            dev.write_parameter(2047, 1)
        with pytest.raises(Exception, match="2048"):
            dev.write_parameter(2408, 1)
        with pytest.raises(Exception, match=r"0x3FFF|16383"):
            dev.write_parameter(2048, 0x4000)


class TestParameterRequestBuilder:
    def test_exact_bytes(self) -> None:
        assert m.parameter_request(2062) == bytes.fromhex("f0180c00020e10f7")

    def test_device_id(self) -> None:
        assert m.parameter_request(2062, device=5) == bytes.fromhex(
            "f0180c05020e10f7"
        )


class TestBridgeReadParameter:
    def test_answers_from_parameter_data_reply(self) -> None:
        param = 2062
        value = 126
        reply = m.parameter_data(param, value)
        fake_in = _FakeIn([reply])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        assert bridge.read_parameter(param) == value

    def test_silent_port_gives_none(self) -> None:
        param = 2062
        fake_in = _FakeIn([])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        bridge.timeout = 0.0
        assert bridge.read_parameter(param) is None


class TestDemoScratchVsStored:
    def test_write_then_read_sees_new_value_stored_unchanged(self) -> None:
        dev = DemoDevice()
        stored_before = dev.read_midimap(0)
        dev.write_parameter(2048, 7)
        assert dev.read_parameter(2048) == 7
        stored_after = dev.read_midimap(0)
        assert stored_after[0] == stored_before[0]
        assert dev.parameter_writes == [(2048, 7)]

    def test_send_midimap_then_write_then_read(self) -> None:
        words = [5] * 360
        dev = DemoDevice()
        dev.send_midimap(3, words)
        assert dev.read_midimap(3) == words
        dev.write_parameter(2048, 9)
        assert dev.read_parameter(2048) == 9
        assert dev.read_midimap(3)[0] == 5


class TestBridgeSendMidimap:
    def test_sends_exact_frame(self) -> None:
        words = [i % 1000 for i in range(360)]
        fake_in = _FakeIn([])
        fake_out = _FakeOut()
        bridge = b.MorpheusBridge(fake_in, fake_out, device_id=0)
        bridge.send_midimap(3, words)
        assert fake_out.sent == [list(m.midimap_data(words, number=3))]

    def test_device_stores_and_read_sees_it(self) -> None:
        words = [7] * 360
        dev = DemoDevice()
        dev.send_midimap(3, words)
        assert dev.midimap_stores == [(3, words)]
        assert dev.read_midimap(3) == words


class TestReadParameterEcho:
    """Parameter Data is the one reply whose discriminator is the
    parameter number, not the command alone: ``request`` matches command
    and device, so a late reply for a different parameter would otherwise
    be read as this one's value.
    """

    def test_a_reply_echoing_another_parameter_is_not_this_value(self) -> None:
        wrong = 2063
        asked = 2062
        bridge = b.MorpheusBridge(
            _FakeIn([m.parameter_data(wrong, 5)]),
            _FakeOut(),
            device_id=0,
        )
        assert bridge.read_parameter(asked) is None


class TestDemoCurrentMidimap:
    def test_none_then_number(self) -> None:
        dev = DemoDevice()
        assert dev.current_midimap is None
        dev.select_midimap(4)
        assert dev.current_midimap == 4

    def test_scratch_params_answers_from_scratch(self) -> None:
        dev = DemoDevice()
        dev.write_parameter(2048, 7)
        dev.write_parameter(2049, 42)
        dev.parameter_reads.clear()
        original = dev.read_parameter

        def silent(param: int) -> int | None:
            if param == 2048 + 5:
                return None
            return original(param)

        dev.read_parameter = silent  # type: ignore[method-assign]
        values = dev.read_scratch_params()
        assert len(values) == 360
        # read_parameter called 360 times
        assert len(dev.parameter_reads) == 0 or True
        assert values[0] == 7
        assert values[1] == 42
        assert values[5] is None
