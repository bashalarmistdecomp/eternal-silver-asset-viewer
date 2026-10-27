"""The environment a system program is started with (decoders._env.system_env)."""

import sys

from decoders._env import system_env


def test_from_source_a_system_program_inherits_ours(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert system_env() is None


def test_frozen_the_user_s_own_library_path_goes_back(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/unpacked")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/mine")
    env = system_env()
    assert env["LD_LIBRARY_PATH"] == "/mine" and "LD_LIBRARY_PATH_ORIG" not in env


def test_frozen_with_none_of_the_user_s_own_there_is_none(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/unpacked")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    assert "LD_LIBRARY_PATH" not in system_env()
