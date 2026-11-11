"""WIPEOUT entities: the mask with its placement frame and clip boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

import ezdwg
from ezdwg import raw

ROOT = Path(__file__).resolve().parents[1]
# The same drawing saved as R2000, R2007, R2010, R2013 and R2018. It holds one
# WIPEOUT, in model space on layer "0".
SAMPLES = {
    version: ROOT / f"test_dwg/acadsharp/sample_{version}.dwg"
    for version in ("AC1015", "AC1021", "AC1024", "AC1027", "AC1032")
}
WIPEOUT_HANDLE = 0x44D
FRAME = 31.707742926072683
HALF = 0.5
BOUNDARY = [
    (-HALF, HALF),
    (0.3260511008800897, 0.49206350233605894),
    (0.2505944934505404, -0.21031745948902658),
    (-0.47617156637515023, -HALF),
]


@pytest.mark.parametrize("version", sorted(SAMPLES))
def test_wipeout_is_read_with_its_frame_and_boundary(version: str) -> None:
    path = SAMPLES[version]
    assert path.exists(), f"missing sample: {path}"
    doc = ezdwg.read(str(path))

    (wipeout,) = doc.entities().query("WIPEOUT")
    assert wipeout.handle == WIPEOUT_HANDLE
    dxf = wipeout.dxf
    assert dxf["insert"] == pytest.approx((271.9211288808192, 3.988123351850959, 0.0))
    assert dxf["u_vector"] == pytest.approx((FRAME, 0.0, 0.0))
    assert dxf["v_vector"] == pytest.approx((0.0, FRAME, 0.0))
    assert dxf["size"] == (1.0, 1.0)
    assert dxf["display_props"] == 7
    assert dxf["clipping"] is True
    assert (dxf["brightness"], dxf["contrast"], dxf["fade"]) == (50, 50, 0)
    assert dxf["clip_type"] == 2
    # The clip mode came with R2010.
    assert dxf["clip_mode"] == (None if version in {"AC1015", "AC1021"} else 0)
    assert dxf["clip_vertices"] == BOUNDARY
    assert dxf["layer_handle"] == 0x10
    assert doc.entity_placement(wipeout.handle) == (2, None)


@pytest.mark.parametrize("version", sorted(SAMPLES))
def test_wipeout_is_one_of_the_entities_of_a_layout(version: str) -> None:
    doc = ezdwg.read(str(SAMPLES[version]))
    by_type: dict[str, int] = {}
    for entity in doc.modelspace().iter_entities():
        by_type[entity.dxftype] = by_type.get(entity.dxftype, 0) + 1
    assert by_type["WIPEOUT"] == 1
    # The record is the one of IMAGE, but the two types stay apart.
    assert WIPEOUT_HANDLE not in [e.handle for e in doc.entities().query("IMAGE")]


def test_raw_wipeout_rows() -> None:
    rows = raw.decode_wipeout_entities(str(SAMPLES["AC1032"]))
    assert len(rows) == 1
    (
        handle,
        insert,
        u_vector,
        v_vector,
        size,
        display_props,
        clipping,
        levels,
        clip_type,
        clip_mode,
        clip_vertices,
    ) = rows[0]
    assert handle == WIPEOUT_HANDLE
    assert insert == pytest.approx((271.9211288808192, 3.988123351850959, 0.0))
    assert u_vector == pytest.approx((FRAME, 0.0, 0.0))
    assert v_vector == pytest.approx((0.0, FRAME, 0.0))
    assert size == (1.0, 1.0)
    assert (display_props, clipping, levels) == (7, True, (50, 50, 0))
    assert (clip_type, clip_mode) == (2, 0)
    assert clip_vertices == BOUNDARY


def test_drawing_without_a_wipeout_gives_no_rows(tmp_path) -> None:
    doc = ezdwg.new("AC1032")
    doc.modelspace().add_line((0, 0, 0), (1, 0, 0))
    path = tmp_path / "plain.dwg"
    doc.save(path)

    assert raw.decode_wipeout_entities(str(path)) == []
    assert list(ezdwg.read(str(path)).entities().query("WIPEOUT")) == []
