"""R2004 classes section: every class of the drawing gets its name."""

from __future__ import annotations

from pathlib import Path

from ezdwg import raw

ROOT = Path(__file__).resolve().parents[1]
# One of its classes has a maintenance version above 255.
SAMPLE = ROOT / "test_dwg/acadsharp/sample_AC1018.dwg"
FIRST_CLASS_NUMBER = 500


def test_r2004_class_based_objects_have_their_class_names() -> None:
    assert SAMPLE.exists(), f"missing sample: {SAMPLE}"
    names_by_code: dict[int, str] = {}
    for _handle, _offset, _size, type_code, type_name, _type_class in raw.list_object_headers_with_type(
        str(SAMPLE)
    ):
        if type_code >= FIRST_CLASS_NUMBER:
            names_by_code[type_code] = type_name

    assert len(names_by_code) == 42
    assert not [name for name in names_by_code.values() if name.startswith("UNKNOWN")]
    # A class in front of the one with the large version, and classes after it.
    assert {"DICTIONARYVAR", "MLEADERSTYLE", "SORTENTSTABLE", "IMAGE"} <= set(
        names_by_code.values()
    )
