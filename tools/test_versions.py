"""tools/versions.py on a made-up repository: the app's version files as
the real ones are laid out, a page, a backend with tests, documents.

Run from the top: .venv/bin/python3 -m pytest -p no:cacheprovider tools
"""

import json
import subprocess

import pytest

import versions

V = "0.2.0"


def _package(version=V, deps=None, scripts=None):
    return {"name": "made-up", "version": version, "private": True,
            "scripts": scripts or {"build": "vite build"},
            "dependencies": deps or {"a": "^1.0.0"},
            "devDependencies": {"d": "^1.0.0"}}


def _lock(version=V, a="1.0.0", d="1.0.0"):
    return {"name": "made-up", "version": version, "lockfileVersion": 3, "requires": True,
            "packages": {
                "": {"name": "made-up", "version": version,
                     "dependencies": {"a": "^1.0.0"}, "devDependencies": {"d": "^1.0.0"}},
                "node_modules/a": {"version": a, "dependencies": {"b": "^2.0.0"}},
                "node_modules/a/node_modules/b": {"version": "2.0.0"},
                "node_modules/b": {"version": "1.0.0"},
                "node_modules/d": {"version": d, "dev": True}}}


def _write(root, path, text):
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)


def _json(root, path, value):
    _write(root, path, json.dumps(value, indent=2) + "\n")


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "core.hooksPath=/dev/null", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """main at 0.2.0, and a branch `work` off it with nothing changed."""
    _json(tmp_path, "app/package.json", _package())
    _json(tmp_path, "app/package-lock.json", _lock())
    _json(tmp_path, "app/src-tauri/tauri.conf.json",
          {"productName": "x", "version": "../package.json", "identifier": "x"})
    _write(tmp_path, "app/src-tauri/Cargo.toml",
           f'[package]\nname = "{versions.CRATE}"\nversion = "{V}"\nedition = "2024"\n\n'
           '[dependencies.serde]\nversion = "1"\n')
    _write(tmp_path, "app/src-tauri/Cargo.lock",
           f'[[package]]\nname = "{versions.CRATE}"\nversion = "{V}"\n\n'
           '[[package]]\nname = "serde"\nversion = "1.0.0"\n')
    _write(tmp_path, "backend/server.py", f'import sys\n\nVERSION = "{V}"\n')
    _write(tmp_path, "backend/decoders/tests/test_one.py", "def test_one():\n    pass\n")
    _write(tmp_path, "app/src/App.tsx", "export {}\n")
    _write(tmp_path, "README.md", "made up\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "first")
    _git(tmp_path, "checkout", "-q", "-b", "work")
    return tmp_path


def _run(root, *args):
    return versions.main(list(args), root=root)


def _said(root):
    return {(p.file, p.what): v for p, v in versions.read(root)}


def test_nothing_changed_passes(repo, capsys):
    assert _run(repo) == 0
    assert "nothing the app ships changed since main" in capsys.readouterr().out


def test_documents_and_tests_move_nothing(repo):
    _write(repo, "README.md", "changed\n")
    _write(repo, "backend/decoders/tests/test_one.py", "def test_one():\n    assert 1\n")
    _write(repo, "backend/decoders/tests/test_two.py", "")       # new, not yet added
    assert _run(repo) == 0


def test_a_shipped_file_changed_asks_for_a_patch_step(repo, capsys):
    _write(repo, "app/src/App.tsx", "export const x = 1\n")
    _write(repo, "backend/new.py", "")                            # new, not yet added
    assert _run(repo) == 1
    out = capsys.readouterr().out
    assert "app/src/App.tsx" in out and "backend/new.py" in out
    assert "it is to be 0.2.1" in out


def test_move_writes_the_step_in_every_place(repo):
    _write(repo, "app/src/App.tsx", "export const x = 1\n")
    assert _run(repo, "--move") == 0
    said = _said(repo)
    assert said.pop(("app/src-tauri/tauri.conf.json", "its version")) == "../package.json"
    assert set(said.values()) == {"0.2.1"}
    # the rest of each file as it was
    lock = json.loads((repo / "app/package-lock.json").read_text(encoding="utf-8"))
    assert lock == _lock("0.2.1")
    assert 'version = "1"' in (repo / "app/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "serde"\nversion = "1.0.0"' in (repo / "app/src-tauri/Cargo.lock").read_text(encoding="utf-8")
    # moved once, a second --move and more work leave it there
    _write(repo, "app/src/App.tsx", "export const x = 2\n")
    assert _run(repo, "--move") == 0
    assert _said(repo)[("app/package.json", "its version")] == "0.2.1"


def test_set_writes_the_owners_version_and_refuses_one_before(repo, capsys):
    assert _run(repo, "--set", "0.3.0") == 0
    assert _said(repo)[("backend/server.py", "VERSION")] == "0.3.0"
    assert _run(repo, "--set", "0.1.9") == 2
    assert "before 0.2.0" in capsys.readouterr().err


def test_a_copy_that_disagrees_fails(repo, capsys):
    _write(repo, "backend/server.py", 'import sys\n\nVERSION = "0.2.5"\n')
    assert _run(repo) == 1
    assert "backend/server.py: VERSION says '0.2.5', not '0.2.0'" in capsys.readouterr().out


def test_tauri_reads_package_json(repo, capsys):
    _json(repo, "app/src-tauri/tauri.conf.json", {"productName": "x", "version": V, "identifier": "x"})
    assert _run(repo) == 1
    assert "not '../package.json'" in capsys.readouterr().out
    assert _run(repo, "--move") == 0                            # the source written back, and
    said = _said(repo)                                            # the step, the file shipping
    assert said[("app/src-tauri/tauri.conf.json", "its version")] == "../package.json"
    assert said[("app/package.json", "its version")] == "0.2.1"


def test_a_version_that_went_back_fails(repo, capsys):
    _git(repo, "checkout", "-q", "main")
    _json(repo, "app/package.json", _package("0.3.0"))
    _git(repo, "commit", "-q", "-am", "0.3.0 on main")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "main")                             # the work takes main's 0.3.0 …
    versions.write(repo, "0.2.9")                                 # … and goes back
    assert _run(repo) == 1
    assert "went back: 0.2.9, and main has 0.3.0" in capsys.readouterr().out


def test_package_json_ships_by_its_dependencies(repo, capsys):
    _json(repo, "app/package.json", _package(scripts={"build": "vite build --mode x"}))
    assert _run(repo) == 0
    _json(repo, "app/package.json", _package(deps={"a": "^1.1.0"}))
    assert _run(repo) == 1
    assert "app/package.json (its dependencies)" in capsys.readouterr().out


def test_the_lock_ships_by_the_packages_the_app_carries(repo, capsys):
    _json(repo, "app/package-lock.json", _lock(d="1.0.1"))       # a build tool's
    assert _run(repo) == 0
    _json(repo, "app/package-lock.json", _lock(a="1.0.1"))       # the page's
    assert _run(repo) == 1
    assert "app/package-lock.json (the packages the app carries)" in capsys.readouterr().out


def test_carried_finds_a_package_as_npm_does():
    lock = _lock()
    got = versions.carried(_package(), lock)
    # a's b is the one nested under it, not the top one; d is a build tool's
    assert set(got) == {"node_modules/a", "node_modules/a/node_modules/b"}


def test_ships():
    assert versions.ships("backend/viewer_server/library.py")
    assert versions.ships("app/src-tauri/icons/icon.png")
    assert versions.ships("app/src-tauri/Cargo.lock")
    for path in ("backend/viewer_server/tests/test_import.py", "backend/conftest.py",
                 "backend/decoders/testing.py", "backend/requirements-dev.txt",
                 "app/src-tauri/.gitignore", "tools/brand/build.mjs", "docs/img/logo.png",
                 "README.md", "app/package.json", "app/.oxlintrc.json"):
        assert not versions.ships(path), path


def test_a_place_not_found_is_refused(repo, capsys):
    _write(repo, "backend/server.py", "import sys\n")
    assert _run(repo) == 2
    assert "backend/server.py: VERSION is not where it is written" in capsys.readouterr().err


def test_a_base_with_no_common_history_is_refused(repo, capsys):
    assert _run(repo, "--base", "nowhere") == 2
    assert "versions: git merge-base" in capsys.readouterr().err
