"""The saved picture (proxy graphic) of an entity, by handle."""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

import ezdwg
from ezdwg import raw

ROOT = Path(__file__).resolve().parents[1]
# The same drawing saved in seven versions, with the same handles.
SAMPLES = {
    version: ROOT / f"test_dwg/acadsharp/sample_{version}.dwg"
    for version in ("AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032")
}
# The entities of the sample that carry a saved picture, by type: how many,
# and the checksum (CRC-32) over their pictures joined in handle order. The
# numbers come from a cut of the raw records made by hand in Python, not from
# the function under test.
SAME_IN_EVERY_VERSION = {
    "IMAGE": (1, 0x4543C3FB),
    "MESH": (2, 0x74450D63),
    "PDFUNDERLAY": (1, 0xB6C7C4DC),
    "WIPEOUT": (1, 0x0413343A),
}
PICTURES = {
    "AC1014": {"ACAD_TABLE": (2, 0x1A4EDE5D), "MULTILEADER": (15, 0x5C8FF03B)},
    "AC1015": {"ACAD_TABLE": (2, 0x823C4B06), "MULTILEADER": (15, 0x5A7DA78D)},
    "AC1018": {"ACAD_TABLE": (2, 0x3852CAF9), "MULTILEADER": (15, 0x4FDBBC7E)},
    "AC1021": {"ACAD_TABLE": (2, 0x073BA159), "MULTILEADER": (15, 0xF0E4F97C)},
    "AC1024": {"ACAD_TABLE": (2, 0x47CA0352), "MULTILEADER": (15, 0xBF2E77DA)},
    "AC1027": {"ACAD_TABLE": (2, 0xED666B2B), "MULTILEADER": (15, 0x2E58F5C4)},
    "AC1032": {"ACAD_TABLE": (2, 0xB3C4FEE3), "MULTILEADER": (15, 0x41B601C3)},
}
# The bytes of the 15 MULTILEADER pictures in all. They are longer from R2007
# on.
MLEADER_BYTES = {"AC1014": 14012, "AC1015": 14012, "AC1018": 14012}
MLEADER_BYTES_FROM_R2007 = 15160
# The first MULTILEADER of the sample and the size of its picture in R2000.
FIRST_MLEADER = 0x7B8
FIRST_PICTURE_SIZE = 780


def _objects(path: Path) -> tuple[dict[int, str], list[int]]:
    """The entities of a drawing (handle to type name) and the handles of its other objects."""
    rows = raw.list_object_headers_with_type(str(path))
    entities = {row[0]: row[4] for row in rows if row[5] == "E"}
    return entities, [row[0] for row in rows if row[0] not in entities]


@pytest.mark.parametrize("version", sorted(SAMPLES))
def test_saved_pictures_of_the_sample_by_type(version: str) -> None:
    path = SAMPLES[version]
    assert path.exists(), f"missing sample: {path}"
    entities, _others = _objects(path)

    rows = raw.decode_entity_proxy_graphics(str(path), sorted(entities))
    # Every entity reads; most have no saved picture.
    assert [handle for handle, _picture in rows] == sorted(entities)
    by_type: dict[str, list[bytes]] = {}
    for handle, picture in rows:
        if picture is not None:
            assert type(picture) is bytes
            by_type.setdefault(entities[handle], []).append(picture)

    found = {
        name: (len(pictures), zlib.crc32(b"".join(pictures)))
        for name, pictures in by_type.items()
    }
    assert found == {**SAME_IN_EVERY_VERSION, **PICTURES[version]}
    assert sum(map(len, by_type["MULTILEADER"])) == MLEADER_BYTES.get(
        version, MLEADER_BYTES_FROM_R2007
    )


@pytest.mark.parametrize("version", sorted(SAMPLES))
def test_rows_follow_the_handles_asked(version: str) -> None:
    path = SAMPLES[version]
    entities, others = _objects(path)
    line = next(handle for handle, name in entities.items() if name == "LINE")

    # One row for each handle asked, in the order asked; a handle that is not
    # in the drawing has no row.
    rows = raw.decode_entity_proxy_graphics(
        str(path), [line, FIRST_MLEADER, 0xFFFFFFF0, line, FIRST_MLEADER]
    )
    assert [handle for handle, _picture in rows] == [line, FIRST_MLEADER, line, FIRST_MLEADER]
    assert rows[0][1] is None and rows[2][1] is None
    assert rows[1][1] and rows[1][1] == rows[3][1]

    assert raw.decode_entity_proxy_graphics(str(path), []) == []
    # An object that is not an entity has no saved picture and no row: its
    # record has other fields where an entity has the flag.
    assert len(others) > 100
    assert raw.decode_entity_proxy_graphics(str(path), others) == []


def _bits(data: bytes, bit: int, count: int) -> int:
    return (int.from_bytes(data, "big") >> (len(data) * 8 - bit - count)) & ((1 << count) - 1)


def _with_bits(data: bytes, bit: int, count: int, value: int) -> bytes:
    """`data` with `value` written over `count` bits from `bit` on."""
    low = len(data) * 8 - bit - count
    stream = int.from_bytes(data, "big") & ~(((1 << count) - 1) << low)
    return (stream | (value << low)).to_bytes(len(data), "big")


def _first_mleader_fields(source: bytes) -> tuple[int, int, int]:
    """Bit offsets in the R2000 sample of the handle, the flag and the size of the first MULTILEADER's picture."""
    path = str(SAMPLES["AC1015"])
    ((handle, offset, _size, _code, _record),) = raw.read_object_records_by_handle(
        path, [FIRST_MLEADER]
    )
    ((_handle, picture),) = raw.decode_entity_proxy_graphics(path, [FIRST_MLEADER])
    assert (handle, len(picture)) == (FIRST_MLEADER, FIRST_PICTURE_SIZE)
    # R2000 stores its objects as plain bits. The record begins with its size
    # (16 bits), the type of a class (2 + 16 bits) and the size of the object
    # data (32 bits); then comes the handle: a byte with its length, 2 here,
    # and its two bytes.
    handle_bit = offset * 8 + 16 + 18 + 32
    assert _bits(source, handle_bit, 24) == 0x02_0000 | FIRST_MLEADER
    # The picture is in the file once, at some bit; its size is the raw long
    # in front of it and the flag is the bit in front of the size.
    total = len(source) * 8
    stream = int.from_bytes(source, "big")
    found = []
    for shift in range(8):
        shifted = ((stream << shift) & ((1 << total) - 1)).to_bytes(len(source), "big")
        at = shifted.find(picture)
        while at >= 0:
            found.append(at * 8 + shift)
            at = shifted.find(picture, at + 1)
    (picture_bit,) = found
    size_bit = picture_bit - 32
    assert _bits(source, size_bit, 32) == int.from_bytes(
        FIRST_PICTURE_SIZE.to_bytes(4, "little"), "big"
    )
    assert _bits(source, size_bit - 1, 1) == 1
    return handle_bit, size_bit - 1, size_bit


def _mleader_rows(tmp_path, data: bytes) -> list[tuple[int, bytes | None]]:
    path = tmp_path / "changed.dwg"
    path.write_bytes(data)
    return raw.decode_entity_proxy_graphics(str(path), [FIRST_MLEADER, 0xB1A])


def _raw_long(value: int) -> int:
    return int.from_bytes(value.to_bytes(4, "little"), "big")


def test_picture_with_a_size_past_its_record_is_left_out(tmp_path) -> None:
    source = SAMPLES["AC1015"].read_bytes()
    _handle_bit, _flag_bit, size_bit = _first_mleader_fields(source)
    whole = dict(_mleader_rows(tmp_path, source))
    assert len(whole[FIRST_MLEADER]) == FIRST_PICTURE_SIZE

    # A smaller size reads: the same bytes, cut short.
    rows = _mleader_rows(tmp_path, _with_bits(source, size_bit, 32, _raw_long(700)))
    assert dict(rows) == {FIRST_MLEADER: whole[FIRST_MLEADER][:700], 0xB1A: whole[0xB1A]}

    # The record is about 1,000 bytes long. A size past it leaves the entity out;
    # the caller sees one row less than the handles it asked.
    for size in (1100, 0x7FFFFFFF, 0xFFFFFFFF):
        rows = _mleader_rows(tmp_path, _with_bits(source, size_bit, 32, _raw_long(size)))
        assert rows == [(0xB1A, whole[0xB1A])], size


def test_picture_of_no_bytes_and_flag_off(tmp_path) -> None:
    source = SAMPLES["AC1015"].read_bytes()
    _handle_bit, flag_bit, size_bit = _first_mleader_fields(source)

    empty = _mleader_rows(tmp_path, _with_bits(source, size_bit, 32, 0))
    assert empty[0] == (FIRST_MLEADER, b"")
    absent = _mleader_rows(tmp_path, _with_bits(source, flag_bit, 1, 0))
    assert absent[0] == (FIRST_MLEADER, None)
    assert empty[1] == absent[1] and empty[1][1]


def test_record_that_holds_another_handle_is_left_out(tmp_path) -> None:
    source = SAMPLES["AC1015"].read_bytes()
    handle_bit, _flag_bit, _size_bit = _first_mleader_fields(source)
    # The object list still names the record by the handle 0x7B8; the record
    # itself now says 0x7B9.
    changed = _with_bits(source, handle_bit + 8, 16, FIRST_MLEADER + 1)
    rows = _mleader_rows(tmp_path, changed)
    assert [handle for handle, _picture in rows] == [0xB1A]


def test_drawing_written_by_the_library_has_no_saved_pictures(tmp_path) -> None:
    doc = ezdwg.new("AC1032")
    doc.modelspace().add_line((0, 0, 0), (1, 0, 0))
    path = tmp_path / "plain.dwg"
    doc.save(path)

    entities, _others = _objects(path)
    rows = raw.decode_entity_proxy_graphics(str(path), sorted(entities))
    assert rows and all(picture is None for _handle, picture in rows)
