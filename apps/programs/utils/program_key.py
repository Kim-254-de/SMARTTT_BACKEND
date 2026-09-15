"""
Programs get created independently by every timetable upload batch
(apps.timetable.services.mapper.resolve_program /
apps.uploads.services.timetable_mapping_service), matched loosely against
whatever department text is on that row. Two uploads that spell the same
program identically but tag it with slightly different department text
(e.g. "Computer Science" vs "School of Computer Science") end up creating
two distinct Program rows with the *same name* under two different
Department rows — because Program.unique_together is scoped to
(department, name)/(department, code), not name/code alone.

canonical_program_key() gives a formatting-insensitive comparison key so
call sites that need to treat "same-looking" programs as one thing (e.g.
building a course dropdown) can group by it. It only smooths over
formatting differences (case, punctuation, whitespace) — it does NOT
resolve genuinely different wording for the same program (e.g. an
abbreviated "BSC COMP SCI" vs a spelled-out "BSC COMPUTER SCIENCE").
That kind of variant needs a human-curated alias, not a normalizer,
because collapsing it automatically risks merging two different programs
that happen to share an abbreviation.
"""
import re


def canonical_program_key(name: str) -> str:
    """Formatting-insensitive comparison key for a program name."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())
