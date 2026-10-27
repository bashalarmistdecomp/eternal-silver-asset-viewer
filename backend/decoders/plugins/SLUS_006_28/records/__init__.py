"""RAM/EXE-resident game record layouts.

The distinction with the sibling packages: `formats/` parses files on
disc, `records/` parses in-memory structures (stat tables, item
definitions, encounter records). Pure byte parsers, source-agnostic —
the same code reads the EXE image or any other copy of those bytes.

Layouts mirror the evidence in `docs/spec/code/subsystems/*.md`; the
JSON export schemas live in `docs/spec/battle-data.md`. Do not add
speculative fields here — unknown offsets stay unknown, and the raw
bytes travel with every parsed record so nothing is lost.
"""

#: The program whose register names and addresses these layouts are
#: written by. The Japanese program, SLPS_013.97, is read by the same
#: code: `programs` tells the two apart by their build stamp and gives
#: each table's address in the Japanese program, where it was located.
#: Reading a table against another executable produces plausible numbers
#: rather than an error, so a reader asks `programs.address` for every
#: table it reads.
PROGRAM: str = "SLUS_006.28"
