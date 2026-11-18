"""Parsing of plan build strings.

Secret: the textual grammar of a build string -- the optional "x{jobs}"
suffix, the item/normal/invention/reverse-engineering forms, their
defaults, and how an ambiguous string is resolved against known names.
"""

import re
from dataclasses import dataclass

_JOBS = re.compile(r"^(?P<rest>.*\S)\s+[xX](?P<jobs>\d+)$")
_NORMAL = re.compile(r"^(?P<name>.+?)\s+(?P<runs>\d+)\s+(?P<me>\d+)\s+(?P<te>\d+)$")
_RUNS = re.compile(r"^(?P<name>.+?)\s+(?P<runs>\d+)$")


@dataclass(frozen=True)
class BuildRequest:
    name: str
    runs: int
    jobs: int
    me: int = 0
    te: int = 0
    decryptor: str = None  # set (possibly "None") only for invention
    relic: str = None  # set only for reverse engineering

    @property
    def invented(self):
        return self.decryptor is not None


def _invention_pattern(decryptors):
    choices = "|".join(re.escape(d) for d in sorted(decryptors, key=len, reverse=True))
    return re.compile(
        r"^(?P<name>.+?)\s+(?P<runs>\d+)\s+(?P<dec>%s)(?:\s+(?P<relic>.+))?$" % choices,
        re.IGNORECASE,
    )


def parse(text, decryptors, is_item, is_relic):
    """Parse a build string into a BuildRequest.

    decryptors: decryptor names ("None" included); is_item / is_relic:
    predicates telling whether a name is a known product / relic.
    """
    text = " ".join(text.split())
    jobs = 1
    match = _JOBS.match(text)
    if match:
        text, jobs = match.group("rest"), int(match.group("jobs"))

    candidates = []
    match = _NORMAL.match(text)
    if match:
        candidates.append(BuildRequest(
            match.group("name"), int(match.group("runs")), jobs,
            me=int(match.group("me")), te=int(match.group("te")),
        ))
    match = _invention_pattern(decryptors).match(text)
    if match:
        canonical = {d.lower(): d for d in decryptors}
        candidates.append(BuildRequest(
            match.group("name"), int(match.group("runs")), jobs,
            decryptor=canonical[match.group("dec").lower()],
            relic=match.group("relic"),
        ))
    match = _RUNS.match(text)
    if match:
        candidates.append(BuildRequest(match.group("name"), int(match.group("runs")), jobs))
    candidates.append(BuildRequest(text, 1, jobs))

    for request in candidates:
        if is_item(request.name) and (request.relic is None or is_relic(request.relic)):
            return request
    raise LookupError("Cannot parse build string %r" % text)
