"""The model's messages (viewer_tabs.model.Messages) on the user's own SSSC
discs, when the library has them (skipped otherwise; nothing from the disc
enters git).

What this CAN catch: a script that cannot be read as the Dialogue tab reads
it, the Dialogue tab reading a script again that the model read or listing
other messages than a fresh reading's, a label whose walk loses its way (a
label the table does not have), and a portrait outside the 24 portrait files.

What it CANNOT catch: whether a walk's ways are the ones the game takes
(the C each command names) or whether a message is drawn as the game draws it.
"""

import pytest

from decoders import config

_PROGRAM = "SLUS_006.28"
_JP = "SLPS_013.97"

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (config.raw_dir(_PROGRAM) / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _messages(session, program):
    found = [m for m, member in enumerate(session.members) if member.ctx.program == program]
    if not found:
        pytest.skip(f"no {program} disc in the library")
    session.members[found[0]].start()
    return session.model(found[0]).messages


def test_the_dialogue_tab_lists_the_models_reading(session):
    from decoders.plugins.SLUS_006_28.formats import message_window as mw
    from viewer_tabs.tab_providers import DialogueProvider
    msgs = _messages(session, _PROGRAM)
    member = next(m for m in session.members if m.ctx.program == _PROGRAM)
    tab = DialogueProvider()
    assert tab._ensure(member.ctx)
    e = tab._env
    for res in sorted(msgs.by_resource)[::20]:
        assert tab._messages(res) is msgs.by_resource[res]
        assert tab._messages(res) == mw.script_messages(
            e["names"].read_resource(res), e["words"], e["chars"], e["table"], e["font"],
            False, e["commands"])


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_every_script_reads_and_its_labels_reach_messages(session, program):
    msgs = _messages(session, program)
    assert not msgs.errors, msgs.errors
    assert len(msgs.by_resource) > 40
    walked = reached = lost = 0
    for sid in sorted(msgs.resource_of)[::8]:
        known = {m.offset for m in msgs.of_script(sid)}
        for label in msgs.labels(sid):
            walked += 1
            lost += bool(msgs.walk(sid, label).lost)
            found = msgs.of_label(sid, label)
            assert {m.offset for m in found} <= known
            reached += bool(found)
    # most labels show a message; a few jump to a label the table lacks
    assert reached > walked // 2 and lost < walked // 20, (walked, reached, lost)


def test_portraits_are_faces_of_the_24_files(session):
    msgs = _messages(session, _PROGRAM)
    portraits = {p for ms in msgs.by_resource.values() for m in ms for p in msgs.portraits(m)}
    assert portraits and portraits <= set(range(1, 121))
