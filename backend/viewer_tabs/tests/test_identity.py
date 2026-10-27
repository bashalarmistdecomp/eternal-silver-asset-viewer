"""Content digests and tab sources (viewer_tabs.identity)."""

import hashlib
from types import SimpleNamespace

from viewer_tabs import identity


def test_a_file_digest_is_cached_beside_the_file(tmp_path):
    f = tmp_path / "A.STR"
    f.write_bytes(b"made-up movie")
    assert identity.file_digest(f) == hashlib.sha1(b"made-up movie").hexdigest()
    assert "A.STR" in (tmp_path / identity.CACHE_NAME).read_text()


def test_a_changed_file_is_hashed_again(tmp_path):
    f = tmp_path / "A.STR"
    f.write_bytes(b"one")
    first = identity.file_digest(f)
    f.write_bytes(b"other")
    assert identity.file_digest(f) != first


def _ctx(tmp_path, files):
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    return SimpleNamespace(files=tuple(sorted(files)), path=lambda n: tmp_path / n,
                           exe_path=tmp_path / "PROGRAM")


def test_every_tab_compares_its_items_one_by_one():
    from viewer_tabs.tab_providers import PROVIDER_CLASSES
    assert [c.__name__ for c in PROVIDER_CLASSES if not hasattr(c, "item_identity")] == []


def test_a_tab_is_compared_by_the_files_it_requires(tmp_path):
    ctx = _ctx(tmp_path, {"DATA.BIN": b"d", "A.XA": b"a", "B.XA": b"b",
                          "OTHER": b"o", "PROGRAM": b"p"})
    tab = SimpleNamespace(requires=("DATA.BIN", "*.XA"), programs=("X",))
    names = [n for n, _ in identity.tab_sources(tab, ctx)]
    assert names == ["A.XA", "B.XA", "DATA.BIN", "program"]


def test_a_tab_that_declares_nothing_cannot_be_compared(tmp_path):
    ctx = _ctx(tmp_path, {"DATA.BIN": b"d"})
    assert identity.tab_sources(SimpleNamespace(), ctx) is None


def test_parts_are_read_once_and_only_when_compared():
    reads = []

    def parts():
        reads.append(1)
        return [b"ab", b"c"]

    a = identity.of_parts("k", parts)
    assert reads == [] and a.size is None
    b = identity.of_parts("k", lambda: [b"ab", b"c"])
    assert identity.same(a, b) and identity.same(a, b)
    assert reads == [1]


def test_parts_are_told_apart_where_they_split():
    a = identity.of_parts("k", lambda: [b"ab", b"c"])
    b = identity.of_parts("k", lambda: [b"a", b"bc"])
    assert not identity.same(a, b)


def test_a_command_list_is_compared_up_to_its_end():
    import struct
    from viewer_tabs.names import resource_source
    listed = struct.pack("<II", 0x302, 4) + b"made" + struct.pack("<I", 0)
    a = resource_source(listed + b"tail one", 3)        # resource 3: a command list
    b = resource_source(listed + b"other tail", 3)
    assert a == b and b"made" in a
    assert resource_source(b"not a list", 101) == b"not a list"   # a script: whole
