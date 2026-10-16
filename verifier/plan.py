"""RULES.md §5: the order, the plan and one run's quota. Shared, byte for byte, by src/plugin/ and
verifier/.
"""

from __future__ import annotations

from dataclasses import dataclass

from .naming import path_key, suffixed
from .walk import Facts

QUOTA = 60
STAY, MOVE, DELETE = "stay", "move", "delete"
IN_PLACE, RULES, JUNK, EMPTY, COPY = "in-place", "rules", "junk", "empty", "copy"
MAX_NUMBER = 999


@dataclass(frozen=True)
class Step:
    """What the rules do with one file: `i` is its place in the order."""

    i: int
    path: str
    sha256: str
    action: str
    reason: str
    copy_of: int | None
    target: str | None  # where it ends up: its own path for a stay, the move's destination, None for a delete
    quota: bool


def ordered(facts: list[Facts]) -> list[Facts]:
    """Conforming files first, then the others, each part by path in code-point order."""
    return sorted(facts, key=lambda fact: (not fact.conforming, fact.path))


def plan(facts: list[Facts], taken: list[str]) -> list[Step]:
    """Every file's step, in order. `taken` is every path that exists in the folder when the run starts."""
    claimed = {path_key(path) for path in taken}
    kept: dict[str, int] = {}
    steps: list[Step] = []
    pending = 0
    for index, fact in enumerate(ordered(facts)):
        if fact.junk:
            action, reason, copy_of, target = DELETE, JUNK, None, None
        elif fact.size == 0:
            action, reason, copy_of, target = DELETE, EMPTY, None, None
        elif fact.sha256 in kept:
            action, reason, copy_of, target = DELETE, COPY, kept[fact.sha256], None
        elif fact.conforming:
            kept[fact.sha256] = index
            action, reason, copy_of, target = STAY, IN_PLACE, None, fact.path
        else:
            kept[fact.sha256] = index
            target = first_free(fact.base, fact.ext, claimed)
            claimed.add(path_key(target))
            action, reason, copy_of = MOVE, RULES, None
        in_quota = action != STAY and pending < QUOTA
        if action != STAY:
            pending += 1
        steps.append(Step(index, fact.path, fact.sha256, action, reason, copy_of, target, in_quota))
    return steps


def first_free(base: str, ext: str, claimed: set[str]) -> str:
    number = 1
    while path_key(suffixed(base, ext, number)) in claimed:
        number += 1
    return suffixed(base, ext, number)


def nth_free(base: str, ext: str, claimed: set[str], n: int) -> str | None:
    """The n-th name of `base`, `base_2`, ... that is not claimed (n from 1), or None past MAX_NUMBER."""
    number = 0
    while number < MAX_NUMBER:
        number += 1
        name = suffixed(base, ext, number)
        if path_key(name) not in claimed:
            n -= 1
            if n == 0:
                return name
    return None


def hash_length(facts: list[Facts]) -> int:
    """The shortest prefix (12 hex digits or more, in steps of 4) that tells every distinct content apart."""
    digests = sorted({fact.sha256 for fact in facts})
    length = 12
    while length < 64 and len({digest[:length] for digest in digests}) != len(digests):
        length += 4
    return length


def counts(steps: list[Step]) -> dict[str, int]:
    stays = sum(step.action == STAY for step in steps)
    pending = len(steps) - stays
    quota = sum(step.quota for step in steps)
    return {"files": len(steps), "stayed": stays, "pending": pending, "quota": quota, "remaining": pending - quota}
