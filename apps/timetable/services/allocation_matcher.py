"""
Matches parsed allocation rows (allocation_parser.py) to master-timetable slots.

A unit code alone is not enough: common units (COSC 103, EDFO 111, PHIL 210 ...)
are taught to dozens of programmes/years/groups, each by a different lecturer.
Each row is therefore narrowed down, in order, by:

  1. unit code        - exact compact code, else same prefix + same number
                        ignoring zero padding (COSC 130 ~ COSC0130). Never substring.
  2. year / semester  - from the "Y2S1" / "YEAR 2 SEMESTER 1" section heading.
  3. programme        - group letter -> subject combinations defined under the
                        heading ("Group B: KISW/RELI, PE/RELI" -> BED.KISW/RELI,
                        BED.PE/RELI), else the programme title matched against
                        the master programme codes (BACHELOR OF SCIENCE IN ANIMAL
                        SCIENCE -> BSC.ANIMAL SCI).
  4. group            - GR_<letter> class groups, else A/B/C -> stream 1/2/3 when
                        the counts line up.

Every slot gets the lecturer from the most specific row that reached it. Two
equally specific rows naming different lecturers are reported as a conflict and
that slot is left untouched rather than silently letting the last row win.

The module is ORM-free so it can be exercised against parsed timetables offline.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# Specificity of a row -> slot match. Higher wins.
SPEC_YEAR = 1        # unit + year/semester only (programme unknown)
SPEC_PROGRAMME = 2   # + programme
SPEC_GROUP = 3       # + group / subject combination

_STOPWORDS = {"OF", "IN", "AND", "THE", "&", "WITH", "FOR"}

# Subject spellings used in allocation documents vs master programme codes.
_SUBJECT_ALIASES = {
    "GEO": "GEOG", "PHY": "PHYS", "PHYC": "PHYS", "AGR": "AGRI", "ENGL": "ENG",
    "LITT": "LIT", "BUS": "BUST", "BIOL": "BIO", "FRE": "FRENCH", "FREN": "FRENCH",
    "GER": "GERM", "KISW": "KISW", "KIS": "KISW", "CRE": "RELI", "IRE": "IRE",
}

_LEVEL_WORDS = {"DIP": "DIPLOMA", "CERT": "CERTIFICATE"}


@dataclass
class SlotRef:
    id: object
    unit_code: str
    program_code: str
    year_of_study: int
    semester: int | None
    class_group: str = "MAIN"
    stream: str = ""


@dataclass
class RowMatch:
    row: dict
    slot_ids: list = field(default_factory=list)
    specificity: int = 0
    scope: str = ""
    reason: str = ""


def compact_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _code_key(code: str) -> tuple[str, int] | None:
    m = re.match(r"^([A-Z]+)(\d+)$", code)
    return (m.group(1), int(m.group(2))) if m else None


def _subjects(text: str) -> frozenset[str]:
    parts = re.split(r"[/\s]+", text.upper())
    return frozenset(_SUBJECT_ALIASES.get(p, p) for p in parts if p)


def _program_family_and_subjects(program_code: str) -> tuple[str, frozenset[str]]:
    """'BED.BUST/ RELI' -> ('BED', {'BUST', 'RELI'})"""
    family, _, rest = program_code.upper().partition(".")
    return family.strip(), _subjects(rest) if "/" in rest else frozenset()


def _is_abbrev(token: str, word: str) -> bool:
    """
    'SCI' ~ 'SCIENCE' (prefix), 'MNGT' ~ 'MANAGEMENT' (same first letter, in-order
    subsequence; only for 4+ letter tokens, short ones like 'IRM' must be prefixes).
    """
    if not token or not word or token[0] != word[0]:
        return False
    if word.startswith(token):
        return True
    if len(token) < 4:
        return False
    it = iter(word)
    return all(ch in it for ch in token)


def _token_cover(token: str, words: list[str]) -> set[int] | None:
    """
    Heading word indexes a programme-code token stands for, or None. A token either
    abbreviates one word or is an acronym of short prefixes (<= 3 letters) of
    consecutive words: 'AGED' ~ AGricultural EDucation, 'IT' ~ Information
    Technology, 'BSC' ~ Bachelor SCience, 'ECDE' ~ Early Childhood Development Education.
    """
    token = _LEVEL_WORDS.get(token, token)
    for i, w in enumerate(words):
        if _is_abbrev(token, w):
            return {i}

    def seg(tok: str, j: int) -> list[int] | None:
        if not tok:
            return []
        if j >= len(words):
            return None
        for k in range(min(3, len(tok)), 0, -1):
            if words[j].startswith(tok[:k]):
                rest = seg(tok[k:], j + 1)
                if rest is not None:
                    return [j] + rest
        return None

    for start in range(len(words)):
        found = seg(token, start)
        if found and len(found) > 1:
            return set(found)
    return None


_NOISE_WORDS = {
    "INTAKE", "STUDENTS", "STUDENT", "SSP", "GSS", "ODEL", "MAY", "SEP", "SEPT", "SEPTEMBER",
    "JAN", "JANUARY", "N", "C", "X", "XXX",
}
_BROAD_WORDS = {"ARTS", "SCIENCE"}


def _heading_words(heading: str) -> list[str]:
    words = re.findall(r"[A-Z]+", heading.upper())
    return [w for w in words if w not in _STOPWORDS and w not in _NOISE_WORDS]


def program_heading_cover(program_code: str, heading: str) -> int:
    """
    Number of heading words explained by the programme code, 0 if any code token
    has no counterpart. 'BSC.ANIMAL SCI' vs 'BACHELOR OF SCIENCE IN ANIMAL SCIENCE' -> 4.
    For subject-combination codes (BED.BIO/CHEM) only the family ('BED') is
    compared, and the heading may add nothing beyond ARTS/SCIENCE:
    'BACHELOR OF EDUCATION(ARTS)' -> every BED.x/y programme.
    """
    words = _heading_words(heading)
    family, subjects = _program_family_and_subjects(program_code)
    code_part = family if subjects else program_code
    tokens = [t for t in re.split(r"[^A-Z]+", code_part.upper()) if t and t not in _STOPWORDS]
    if not words or not tokens:
        return 0
    covered: set[int] = set()
    for t in tokens:
        c = _token_cover(t, words)
        if c is None:
            return 0
        covered |= c
    if subjects and any(w not in _BROAD_WORDS for i, w in enumerate(words) if i not in covered):
        return 0
    return len(covered)


def program_matches_heading(program_code: str, heading: str) -> bool:
    return program_heading_cover(program_code, heading) > 0


def _program_key(program_code: str) -> str:
    """'BSC AGED' and 'BSC.AGED' are the same programme in the master timetable."""
    return re.sub(r"[^A-Z0-9]", "", program_code.upper())


class AllocationMatcher:
    def __init__(self, slots: list[SlotRef]):
        self.by_code: dict[str, list[SlotRef]] = defaultdict(list)
        self.by_key: dict[tuple[str, int], set[str]] = defaultdict(set)
        self.program_codes = sorted({s.program_code for s in slots})
        self._heading_cache: dict[str, set[str]] = {}
        for s in slots:
            code = compact_code(s.unit_code)
            self.by_code[code].append(s)
            key = _code_key(code)
            if key:
                self.by_key[key].add(code)

    def programmes_for_heading(self, heading: str) -> set[str]:
        """Master programme codes that best explain a programme title (ties kept: 'BSC AGED'/'BSC.AGED')."""
        if heading not in self._heading_cache:
            # An explicit acronym in the title wins: '... BUSINESS INFORMATION TECHNOLOGY (BBIT)'.
            words = set(_heading_words(heading))
            explicit = {p for p in self.program_codes if _program_key(p) in words}
            if explicit:
                self._heading_cache[heading] = explicit
                return explicit
            scores = {p: program_heading_cover(p, heading) for p in self.program_codes} if heading else {}
            best = max(scores.values(), default=0)
            self._heading_cache[heading] = {p for p, sc in scores.items() if best and sc == best}
        return self._heading_cache[heading]

    # -- step 1 ---------------------------------------------------------------
    def _candidate_codes(self, unit_code: str) -> list[str]:
        code = compact_code(unit_code)
        if code in self.by_code:
            return [code]
        key = _code_key(code)
        return sorted(self.by_key.get(key, ())) if key else []

    # -- steps 2-4 --------------------------------------------------------------
    def match_row(self, row: dict) -> RowMatch:
        result = RowMatch(row=row)
        codes = self._candidate_codes(row["unit_code"])
        if not codes:
            result.reason = "Unit not found in master timetable"
            return result
        slots = [s for c in codes for s in self.by_code[c]]

        year, sem = row.get("year_of_study"), row.get("semester")
        if year:
            in_year = [s for s in slots if s.year_of_study == year and (not sem or s.semester in (None, sem))]
            if not in_year:
                years = sorted({f"Y{s.year_of_study}S{s.semester}" for s in slots})
                result.reason = f"Unit is in the master timetable only for {', '.join(years)}, not Y{year}S{sem}"
                return result
            slots = in_year
        spec, scope = SPEC_YEAR, f"Y{year}S{sem}" if year else "any year"

        heading = row.get("programme") or row.get("section") or ""
        group = row.get("group") or ""
        combos = [_subjects(c) for c in row.get("group_combinations") or []]
        if combos:
            in_combo = [s for s in slots if _program_family_and_subjects(s.program_code)[1] in combos]
            same_family = [
                s for s in in_combo
                if program_matches_heading(_program_family_and_subjects(s.program_code)[0], heading)
            ]
            if same_family or in_combo:
                slots = same_family or in_combo
                spec = SPEC_GROUP
                scope = f"{scope} group {group} ({', '.join(row['group_combinations'])})"

        if spec < SPEC_GROUP:
            programmes = self.programmes_for_heading(heading)
            if programmes:
                in_prog = [s for s in slots if s.program_code in programmes]
                if not in_prog:
                    # The programme exists in the master timetable but this unit is not
                    # scheduled for it: never spill the lecturer onto other programmes.
                    result.reason = f"Unit not scheduled for {heading} Y{year}S{sem} in master timetable"
                    return result
                slots, spec = in_prog, SPEC_PROGRAMME
                scope = f"{scope} {', '.join(sorted({s.program_code for s in slots}))}"
            elif len({_program_key(s.program_code) for s in slots}) > 1:
                # Programme title not recognised and the unit is shared by several
                # programmes this year: guessing would put the lecturer on the wrong classes.
                result.reason = (
                    f"Programme '{heading or row.get('section', '')}' not found in master timetable and "
                    f"the unit is shared by {len({_program_key(s.program_code) for s in slots})} programmes"
                )
                return result

        if group:
            own = [s for s in slots if s.class_group.upper() == f"GR_{group}"]
            if own:
                slots, spec, scope = own, SPEC_GROUP, f"{scope} GR_{group}"
            else:
                # Slots explicitly marked for another group are not this row's.
                slots = [s for s in slots if not s.class_group.upper().startswith("GR_")] or slots

        if group and spec < SPEC_GROUP and len({_program_key(s.program_code) for s in slots}) > 1:
            # e.g. 'BOTA 101 G E' under BACHELOR OF EDUCATION(SCIENCE) with no "Group E: ..."
            # definition: which of the BED programmes it covers is unknown.
            result.reason = (
                f"Group {group} has no subject combinations defined in its section, so the "
                f"{len({_program_key(s.program_code) for s in slots})} matching programmes can't be narrowed down"
            )
            return result

        if len({compact_code(s.unit_code) for s in slots}) > 1:
            result.reason = f"Ambiguous unit code, master has {sorted({s.unit_code for s in slots})}"
            return result

        result.slot_ids = [s.id for s in slots]
        result.specificity = spec
        result.scope = scope.strip()
        return result


def normalise_person(name: str) -> str:
    name = re.sub(r"\b(dr|prof|mr|mrs|ms|miss|sister|sr)\b\.?", " ", name, flags=re.IGNORECASE)
    return " ".join(re.sub(r"[^a-z ]", " ", name.lower()).split())


def _row_letters(row: dict, subgroups: dict[str, list[str]] | None = None) -> list[str]:
    """Stream letters a row covers: 'Group V/A&B' -> A, B; plain 'Group V' reuses V's known subgroups."""
    if row.get("subgroups"):
        return row["subgroups"]
    group = row.get("group")
    if not group:
        return []
    return (subgroups or {}).get(group) or [group]


def _resolve_by_stream(sid, rows: list[dict], slot_by_id: dict, claims_slots: dict) -> dict | None:
    """
    Several groups of one section share a programme, e.g. Group A and Group L are
    both ENGL/LIT, or BSC AGED Groups A/B/C. The master timetable splits that
    programme into numbered streams (BED.ENG/LIT ...(1), ...(2)). When the number
    of group letters equals the number of streams, map them in order:
    A -> stream 1, L -> stream 2. Otherwise leave it as a reported conflict.
    """
    known = {r["group"]: r["subgroups"] for r in rows if r.get("group") and r.get("subgroups")}
    if any(not _row_letters(r, known) for r in rows):
        return None
    if len({(r.get("programme"), compact_code(r["unit_code"])) for r in rows}) != 1:
        return None
    slot = slot_by_id[sid]
    if not slot.stream:
        return None
    siblings = [
        slot_by_id[x] for x in claims_slots
        if compact_code(slot_by_id[x].unit_code) == compact_code(slot.unit_code)
        and _program_key(slot_by_id[x].program_code) == _program_key(slot.program_code)
        and slot_by_id[x].year_of_study == slot.year_of_study
    ]
    streams = sorted({s.stream for s in siblings if s.stream})
    letters = sorted({letter for r in rows for letter in _row_letters(r, known)})
    if len(streams) != len(letters):
        return None
    wanted = letters[streams.index(slot.stream)]
    owners = {normalise_person(r["lecturer_name"]): r for r in rows if wanted in _row_letters(r, known)}
    return next(iter(owners.values())) if len(owners) == 1 else None


def plan_assignments(rows: list[dict], slots: list[SlotRef]) -> dict:
    """
    Returns {
      "assignments": {slot_id: (row, scope)},  # slot -> winning allocation row
      "matches":     [RowMatch, ...],          # one per usable row
      "skipped":     [(row, reason), ...],     # placeholders / ODEL / unmatched
      "conflicts":   [ {slot_id, rows} ],      # equally specific rows disagree
    }
    """
    matcher = AllocationMatcher(slots)
    slot_by_id = {s.id: s for s in slots}

    matches, skipped = [], []
    claims: dict[object, list[tuple[int, dict, str]]] = defaultdict(list)
    for r in rows:
        if r.get("placeholder"):
            skipped.append((r, "No lecturer named (department placeholder or blank)"))
            continue
        if r.get("odel"):
            skipped.append((r, "ODEL cohort - not part of the master (GSS) timetable"))
            continue
        m = matcher.match_row(r)
        if not m.slot_ids:
            skipped.append((r, m.reason))
            continue
        matches.append(m)
        for sid in m.slot_ids:
            claims[sid].append((m.specificity, r, m.scope))

    assignments, conflicts = {}, []
    for sid, cl in claims.items():
        top = max(spec for spec, _, _ in cl)
        winners = [(r, scope) for spec, r, scope in cl if spec == top]
        names = {normalise_person(r["lecturer_name"]) for r, _ in winners}
        if len(names) == 1:
            assignments[sid] = winners[0]
            continue
        owner = _resolve_by_stream(sid, [r for r, _ in winners], slot_by_id, claims)
        if owner is not None:
            scope = next(sc for r, sc in winners if r is owner)
            assignments[sid] = (owner, f"{scope} -> stream {slot_by_id[sid].stream}")
        else:
            conflicts.append({"slot_id": sid, "rows": [r for r, _ in winners]})
    return {"assignments": assignments, "matches": matches, "skipped": skipped, "conflicts": conflicts}


def display_lecturer(account_name: str, allocated_name: str) -> str:
    """
    Name to show for a slot. The allocation text wins while the linked account is
    one of the people it names, so co-taught classes ('Luke Mwema / Kevin Tuei')
    keep both names; a different account (reassigned by hand) wins over stale text.
    """
    account_name = (account_name or "").strip()
    allocated_name = (allocated_name or "").strip()
    if allocated_name and account_name:
        account = set(normalise_person(account_name).split())
        named = any(
            set(normalise_person(part).split()) & account for part in allocated_name.split("/") if part.strip()
        )
        return allocated_name if named else account_name
    return allocated_name or account_name
