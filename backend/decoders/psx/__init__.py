"""PSX-GENERIC scope: PlayStation knowledge, no game knowledge.

Sony's own formats (TIM, VAB, SEQ, the ABGR1555 palette), the disc layer,
the PS1 title catalogue, and the EXE-analysis machinery — all of it works
against any PlayStation title. The rule that keeps it that way: no serial
literal and no game's `0x80xxxxxx` address in code under this package,
except in the title catalogue (gamedb), whose job is to name serials, and
in analysis/, which still holds SLUS_006.28's executable seam (exe_loader's
unwrap of its packed program, symbols' tables) until it moves to that
program's plugin.

Title knowledge lives in `decoders.plugins.SLUS_006_28`; the plumbing
(config, inventory, the test builders) stays in the package root.
"""
