"""What every test of the backend shares.

The made-up program images the tests build are zeros where a program
keeps its build stamp, and records.programs answers None for a stamp it
does not know, so that a reader raises rather than read an unknown
program as the US one. Here the empty stamp is the US program's, for the
whole run (it is set as this file is read, before any test module is
imported, since some build their images as they are imported). A test of
an unknown stamp sets programs.STAMPS itself.

A test that reads a disc of the library is marked `disc` and skips when
the library lacks it. With ASSET_VIEWER_REQUIRE_DISCS=1 (a run after a
merge, on a machine whose library holds every disc) such a skip is a
failure instead, so a library that moved cannot pass as green skips.
"""

import os

import pytest

from decoders.plugins.SLUS_006_28.records import programs

programs.STAMPS[programs.stamp_digest(b"")] = programs.US

#: The switch that fails a `disc` test the library cannot serve.
REQUIRE_DISCS = "ASSET_VIEWER_REQUIRE_DISCS"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if (report.skipped and os.environ.get(REQUIRE_DISCS) == "1"
            and item.get_closest_marker("disc") is not None):
        why = report.longrepr[2] if isinstance(report.longrepr, tuple) else report.longrepr
        report.outcome = "failed"
        report.longrepr = f"{REQUIRE_DISCS}=1, and the library cannot serve this test: {why}"
    return report
