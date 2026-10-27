"""Extractions as jobs: one at a time, and a replaced dump forgotten —
made-up jobs and games, no disc.

What this CAN catch: a second extraction started while one runs (each
holds its whole image), or refused once the first only indexes its disc;
a game left
open on a dump that was replaced, or a game that does not hold it closed
with it.

What it CANNOT catch: the extraction itself (test_iso_reader.py, and the
discs the library holds).
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from viewer_server.jobs import Busy, Jobs
from viewer_server.routes import Backend


def _wait(job):
    for _ in range(500):
        if job.state != "running":
            return
        threading.Event().wait(0.01)
    raise AssertionError("the job did not end")


def test_a_job_that_runs_alone_refuses_a_second():
    jobs, go = Jobs(), threading.Event()
    first = jobs.start("extract", lambda job: go.wait(5), alone=True)
    with pytest.raises(Busy):
        jobs.start("extract", lambda job: None, alone=True)
    other = jobs.start("export", lambda job: "another kind runs")
    go.set()
    _wait(first)
    _wait(other)
    assert first.state == "done" and other.result == "another kind runs"
    again = jobs.start("extract", lambda job: "the next", alone=True)
    _wait(again)
    assert again.result == "the next"


def test_a_job_that_lets_go_frees_its_kind_and_goes_on():
    # An extraction indexes its disc last: the staging folder is free by
    # then, and another extraction may start.
    jobs, staged, go = Jobs(), threading.Event(), threading.Event()

    def extract(job):
        job.let_go("index")
        staged.set()
        go.wait(5)
        return "indexed"

    first = jobs.start("extract", extract, alone=True)
    staged.wait(5)
    assert first.describe()["stage"] == "index" and first.state == "running"
    second = jobs.start("extract", lambda job: "the next", alone=True)
    _wait(second)
    go.set()
    _wait(first)
    assert (first.result, second.result) == ("indexed", "the next")


def test_a_failed_job_frees_its_kind():
    jobs = Jobs()

    def fail(job):
        raise ValueError("made-up failure")

    failed = jobs.start("extract", fail, alone=True)
    _wait(failed)
    assert failed.state == "error" and failed.error == "made-up failure"
    _wait(jobs.start("extract", lambda job: None, alone=True))


class _Session:
    def __init__(self, *paths):
        self.games = [SimpleNamespace(path=Path(p)) for p in paths]
        self.closed = False

    def close(self):
        self.closed = True


def test_a_replaced_dump_closes_the_games_holding_it(monkeypatch, tmp_path):
    forgotten = []
    monkeypatch.setattr("viewer_tabs.model.forget", forgotten.append)
    backend = Backend("t", "test")
    holding = _Session(tmp_path / "disc-1", tmp_path / "disc-2")
    other = _Session(tmp_path / "disc-3")
    backend.sessions.update({"aa": holding, "bb": other})
    backend.by_key.update({"made-up": "aa", "made-up-2": "bb"})
    backend.forget(tmp_path / "x" / ".." / "disc-2")
    assert holding.closed and not other.closed
    assert list(backend.sessions) == ["bb"] and backend.by_key == {"made-up-2": "bb"}
    assert forgotten == [(tmp_path / "disc-2").resolve()]
