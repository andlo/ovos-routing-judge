"""The verdict for one golden row, from a Claim.

  hit           the row's skill took it (with the expected intent, when given)
  wrong_intent  the row's skill took it with another intent
  captured      the row's skill was waiting for an answer (get_response /
                converse) and swallowed the utterance as that answer
  other         another skill took it; who it was is in `taker` (a store
                can split this further, e.g. a default skill vs. a neighbour)
  unhandled     nobody took it, or only a pipeline stage with no skill behind it
  hang          nobody took it and the caller saw it time out (a stage that
                did not return, or a device that never answered)

A row without an expected intent is a hit when its skill took it at all.
So is a row whose skill took it with no intent of its own visible (a
handler or speech without a dispatched topic): `wrong_intent` needs
evidence of ANOTHER intent of the same skill.
A row with `"intent_type": "ocp"` must go through OCP's search; one
without is also a hit when OCP handed the sentence to the skill (golden
files written before a skill answered OCP name only its intent).
"""
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from ovos_routing_judge.claim import OCP_FIRED, Claim, is_converse_capture

HIT, WRONG_INTENT, CAPTURED, OTHER, UNHANDLED, HANG = (
    "hit", "wrong_intent", "captured", "other", "unhandled", "hang")
KINDS = (HIT, WRONG_INTENT, CAPTURED, OTHER, UNHANDLED, HANG)
OCP_ROUTE = "ocp"

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATORS = re.compile(r"[._\- ]+")


def normalize_intent(name: str, skill_id: Optional[str] = None) -> str:
    """'<skill_id>:<label>' in one spelling, so the forms a golden file and
    the different cores and workshops use compare equal:

      * `Name.intent` (ovos-workshop 1.x on stable) vs `Name`
      * CamelCase in older releases (`CancelAlert`) vs `cancel_alert`
      * padatious `what.time.is.it` vs padacioso `what_time_is_it`

    A bare label gets `skill_id` as its prefix."""
    name = (name or "").strip()
    if ":" in name:
        skill, _, label = name.partition(":")
    else:
        skill, label = (skill_id or ""), name
    if label.endswith(".intent"):
        label = label[:-len(".intent")]
    label = _CAMEL.sub("_", label).lower()
    label = _SEPARATORS.sub("_", label).strip("_")
    return f"{skill.strip().lower()}:{label}"


def intent_matches(expected: str, fired: Iterable[str], skill_id: str) -> bool:
    want = normalize_intent(expected, skill_id)
    return any(normalize_intent(f, skill_id) == want for f in fired if f and f != OCP_FIRED)


@dataclass(frozen=True)
class Verdict:
    kind: str
    taker: Optional[str] = None
    fired: Tuple[str, ...] = ()   # what fired for the taker
    via: Optional[str] = None     # the taker's best signal: intent, provider, ocp, skill, speak
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.kind == HIT


def describe(claim: Claim, known_ids: Optional[Iterable[str]] = None) -> str:
    """One line on what happened, for a report or a failed step."""
    captures = [i for i in claim.intents if is_converse_capture(i)]
    if captures:
        skill = captures[0].split(":", 1)[0]
        return f"{skill} (captured by its pending get_response/converse - the skill is waiting for an answer)"
    if claim.unmatched:
        return "no skill matched"
    if claim.intents:
        text = ", ".join(claim.intents)
        if claim.provider:
            verb = "played by" if claim.provider_via == "OCP" else "read from"
            return f"{text}, {verb} {claim.provider}"
        return text
    if claim.provider:
        return f"{claim.provider}, via {claim.provider_via}"
    if claim.handlers:
        return ", ".join(claim.handlers)
    if claim.failed:
        return "no skill matched"
    return "nothing matched"


def judge(claim: Claim, own_ids: Iterable[str], expected: Optional[str] = None,
          intent_type: Optional[str] = None, hung: bool = False,
          known_ids: Optional[Iterable[str]] = None, strict_known: bool = True) -> Verdict:
    """The verdict for one row. `own_ids`: the skill ids the row is about
    (a package can register more than one). `known_ids`: the skills loaded
    in this core; when given, only those (and own_ids) can take a row, so a
    pipeline plugin's own intent with no provider behind it is `unhandled`.
    `hung`: the caller gave up waiting. `strict_known=False`: prefer
    `known_ids` but let any skill take a row when none of them did (see
    Claim.taker)."""
    own = set(own_ids)
    known = None if known_ids is None else set(known_ids) | own
    text = describe(claim)

    if claim.captured_by in own:
        return Verdict(CAPTURED, claim.captured_by, tuple(claim.fired(claim.captured_by)),
                       "intent", text)

    taker = claim.taker(known, strict=strict_known)
    if taker is None:
        return Verdict(HANG if hung else UNHANDLED, None, (), None,
                       "no response" if hung and claim.empty else text)

    fired = tuple(claim.fired(taker))
    via = claim.tier_of(taker)
    if taker not in own:
        return Verdict(OTHER, taker, fired, via, text)

    if str(intent_type or "").lower() == OCP_ROUTE:
        ok = OCP_FIRED in fired
    elif not expected:
        ok = True
    else:
        intents = [f for f in fired if f != OCP_FIRED]
        ok = OCP_FIRED in fired or not intents or intent_matches(expected, intents, taker)
    return Verdict(HIT if ok else WRONG_INTENT, taker, fired, via, text)
