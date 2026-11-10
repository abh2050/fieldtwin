"""A guard on every sentence the evidence layer shows. Unsupported claims raise instead of rendering.

The evidence here can support "a plume origin was detected N metres from this registered well" and
"this image covers this location". It cannot support a leak at a well, a cause, an equipment defect,
or a link to any AETHER asset. Negated mentions ("not source attribution") are allowed.
"""

from __future__ import annotations

import re

# Each pattern names a claim the data can't support. Matching ignores case.
_FORBIDDEN = {
    "LEAK_ASSERTED": r"\b(leak(s|ing|ed)?|leakage)\b(?!\s+labels?\b)",
    "CAUSE_ASSERTED": r"\b(caused by|emitted (by|from)|originat(es|ed|ing) (at|from)|came from|"
    r"coming from|responsible for|source of the (plume|emission))\b",
    "ATTRIBUTION_ASSERTED": r"\b(attributed to|attributable to|the source is|is the source|"
    r"source well|emitting well|emitter)\b",
    "DEFECT_ASSERTED": r"\b(defect(ive)?|fault(y|ed)?|damaged|failure|failed equipment|corrosion)\b",
    "CERTAINTY_ASSERTED": r"\b(confirmed|proves?|proven|definitely|certainly|verified emission)\b",
    "DRONE_ASSERTED": r"\b(drone|uav|unmanned aircraft)\b",
    "AETHER_LINK_ASSERTED": r"\b(aether|a-0\d|b-0\d|fl-[ab]-0\d)\b",
}
# Simulated AETHER faults are the point of a synthetic scenario, so naming them there is allowed.
_SYNTHETIC_ALLOWED = {"DEFECT_ASSERTED", "AETHER_LINK_ASSERTED"}
_NEGATION = re.compile(r"\b(not|no|none|never|cannot|can't|isn't|without|nor)\b[^.;:]{0,60}$", re.I)
_COMPILED = {code: re.compile(pattern, re.I) for code, pattern in _FORBIDDEN.items()}


class UnsupportedClaim(ValueError):
    def __init__(self, code: str, text: str):
        super().__init__(f"{code}: {text!r}")
        self.code = code


def violations(text: str, synthetic: bool = False) -> list[str]:
    """Codes of unsupported claims in the text. A claim inside a negated clause doesn't count.

    `synthetic` is for text about a simulated AETHER scenario, which may name fictional assets and
    simulated faults. It never relaxes the rules for real evidence.
    """
    found = []
    for code, pattern in _COMPILED.items():
        if synthetic and code in _SYNTHETIC_ALLOWED:
            continue
        for match in pattern.finditer(text):
            if not _NEGATION.search(text[: match.start()]):
                found.append(code)
                break
    return found


def check(text: str, synthetic: bool = False) -> str:
    """Return the text unchanged, or raise on the first unsupported claim."""
    if codes := violations(text, synthetic):
        raise UnsupportedClaim(codes[0], text)
    return text
