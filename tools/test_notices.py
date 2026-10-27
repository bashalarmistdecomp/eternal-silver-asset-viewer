"""tools/notices.py on made-up packages: the licences judged, what ships
found, and the notices written with each text once."""

import json

import pytest

import notices
from notices import Package


@pytest.mark.parametrize("expression, ok", [
    ("MIT", True),
    ("MIT OR Apache-2.0", True),
    ("MIT/Apache-2.0", True),                       # Cargo's older spelling
    ("(MIT OR Apache-2.0) AND Unicode-3.0", True),
    ("Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT", True),
    ("MIT OR Apache-2.0 OR LGPL-2.1-or-later", True),  # one offered is enough
    ("GPL-3.0-only", False),
    ("MIT AND GPL-3.0-only", False),
    ("LicenseRef-proprietary", False),
    ("", False),
    ("(MIT", False),
])
def test_allowed(expression, ok):
    assert notices.allowed(expression) is ok


def test_a_grant_is_for_its_package_only():
    expr = "GPL-2.0-or-later WITH Bootloader-exception"
    assert not notices.allowed(expr)
    assert notices.allowed(expr, {expr})


def test_elect_chooses_mit_and_a_licence_with_a_text():
    have = {"MIT", "BSD-3-Clause"}
    assert notices.elect("Zlib OR Apache-2.0 OR MIT", have) == ["MIT"]
    assert notices.elect("BSD-3-Clause", have) == ["BSD-3-Clause"]
    assert notices.elect("BSD-3-Clause AND MIT", have) == ["BSD-3-Clause", "MIT"]
    assert notices.elect("Apache-2.0", have) is None


def _crate(name, kind="lib"):
    return {"id": name, "name": name, "version": "1.0.0", "license": "MIT",
            "license_file": None, "manifest_path": f"/nowhere/{name}/Cargo.toml",
            "authors": [f"{name} author <a@b.c>"], "targets": [{"kind": [kind]}]}


def _dep(pkg, kind=None):
    return {"pkg": pkg, "dep_kinds": [{"kind": kind, "target": None}]}


def test_cargo_ships_normal_dependencies_but_not_macros_or_build_scripts():
    meta = {
        "packages": [_crate("app"), _crate("a"), _crate("b"), _crate("m", "proc-macro"),
                     _crate("under-m"), _crate("cc"), _crate("t")],
        "resolve": {"root": "app", "nodes": [
            {"id": "app", "deps": [_dep("a"), _dep("m"), _dep("cc", "build"), _dep("t", "dev")]},
            {"id": "a", "deps": [_dep("b")]},
            {"id": "b", "deps": []},
            {"id": "m", "deps": [_dep("under-m")]},
            {"id": "under-m", "deps": []},
            {"id": "cc", "deps": []},
            {"id": "t", "deps": []},
        ]},
    }
    got = notices.cargo_packages(meta)
    assert [p.name for p in got] == ["a", "b"]
    assert got[0].authors == ["a author"]
    assert got[0].source == "https://crates.io/crates/a/1.0.0"


def test_npm_ships_what_the_dependencies_reach(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps(
        {"dependencies": {"a": "^1"}, "devDependencies": {"tool": "^1"}}))
    lock = {"packages": {
        "": {"dependencies": {"a": "^1"}, "devDependencies": {"tool": "^1"}},
        "node_modules/a": {"version": "1.0.0", "license": "MIT", "dependencies": {"b": "^2"}},
        "node_modules/a/node_modules/b": {"version": "2.0.0", "license": "ISC"},
        "node_modules/b": {"version": "1.0.0", "license": "ISC"},
        "node_modules/tool": {"version": "1.0.0", "license": "GPL-3.0-only", "dev": True},
    }}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    folder = tmp_path / "node_modules" / "a"
    folder.mkdir(parents=True)
    (folder / "LICENSE").write_text("a's licence\n")
    (folder / "package.json").write_text(json.dumps({"license": "MIT", "author": "Someone"}))
    got = notices.npm_packages(tmp_path)
    assert [(p.name, p.version, p.licence) for p in got] == [("a", "1.0.0", "MIT"), ("b", "2.0.0", "ISC")]
    assert got[0].texts == ["a's licence\n"] and got[0].authors == ["Someone"]


STANDARDS = {"MIT": "MIT licence, (c) {holders}\n"}


def test_render_writes_each_text_once_and_fills_in_a_missing_one():
    groups = [("Crates", [Package("a", "1", "MIT", "src-a", ["same text\n"]),
                          Package("b", "2", "MIT OR Apache-2.0", "src-b", ["same text\n"]),
                          Package("c", "3", "Apache-2.0 OR MIT", "src-c", [], ["C Person"])])]
    text, problems = notices.render("Title", groups, STANDARDS)
    assert problems == []
    assert text.count("same text") == 1
    assert "a 1 — MIT — src-a — text 1" in text and "b 2 — MIT OR Apache-2.0 — src-b — text 1" in text
    assert "MIT licence, (c) C Person" in text
    assert "--- 1: a 1, b 2" in text


def test_render_fails_what_the_app_may_not_ship():
    groups = [("Crates", [Package("g", "1", "GPL-3.0-only", "s", ["gpl\n"]),
                          Package("n", "1", "", "s", ["text\n"]),
                          Package("x", "1", "Apache-2.0", "s", [])])]
    _, problems = notices.render("Title", groups, STANDARDS)
    assert problems == ["g 1: GPL-3.0-only is not a licence the app may ship",
                        "n 1: no licence declared",
                        "x 1: ships no licence text, and Apache-2.0 has none here"]


def test_the_bootloader_is_granted_its_exception():
    expr = "GPL-2.0-or-later WITH Bootloader-exception"
    groups = [("Backend", [Package("pyinstaller-bootloader", "6", expr, "s", ["copying\n"]),
                           Package("other", "1", expr, "s", ["copying\n"])])]
    _, problems = notices.render("Title", groups, STANDARDS)
    assert problems == [f"other 1: {expr} is not a licence the app may ship"]


def test_the_mit_text_is_this_repositorys_licence(tmp_path):
    (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted\n")
    mit = notices.standard_texts(tmp_path)["MIT"]
    assert "Copyright (c) {holders}" in mit and "2026 Someone" not in mit
    assert "Permission is hereby granted" in mit


def test_python_names_the_interpreter_and_a_package_with_its_texts():
    got = {p.name.lower(): p for p in notices.python_packages(["pillow"])}
    assert got["python"].licence == "PSF-2.0"
    assert got["pillow"].texts, "Pillow's wheel ships its licence"
    assert notices.allowed(got["pillow"].licence)


def test_a_text_that_names_no_one_is_borrowed_from_another_package():
    mpl = "Mozilla Public License Version 2.0\n==================================\n"
    groups = [("Crates", [Package("has", "1", "MPL-2.0", "s", [mpl]),
                          Package("lacks", "1", "MPL-2.0", "s", [])])]
    text, problems = notices.render("Title", groups, STANDARDS)
    assert problems == []
    assert text.count("Mozilla Public License") == 1 and "--- 1: has 1, lacks 1" in text
