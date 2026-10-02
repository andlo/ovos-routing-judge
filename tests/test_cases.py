"""The shared verdicts. tests/fixtures/cases.json is the contract every
tool using this judge agrees on: add a case there when a core changes its
signals, and every user of the package gets the fix."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ovos_routing_judge import Claim, in_session, judge, normalize_intent

CASES = json.loads((Path(__file__).parent / "fixtures" / "cases.json").read_text())


def _messages(case):
    out = []
    for m in case["messages"]:
        msg_type, data = m[0], m[1]
        context = m[2] if len(m) > 2 else {}
        if case.get("as_dicts"):
            out.append({"type": msg_type, "data": data, "context": context})
        else:
            out.append(SimpleNamespace(msg_type=msg_type, data=data, context=context))
    return out


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_case(case):
    known = None if case.get("no_known") else case["known"]
    claim = Claim.from_messages(_messages(case), known or (), session_id=case.get("session"))
    v = judge(claim, case["own"], expected=case.get("expected"), intent_type=case.get("intent_type"),
              hung=case.get("hung", False), known_ids=known, strict_known=case.get("strict", True))
    assert v.kind == case["kind"], v
    for key in ("taker", "via", "detail"):
        if key in case:
            assert getattr(v, key) == case[key], v
    if "fired" in case:
        assert list(v.fired) == case["fired"]


def test_incremental_equals_batch():
    case = next(c for c in CASES if c["name"] == "reading pipeline fetches from the provider")
    claim = Claim()
    for m in _messages(case):
        claim.observe(m, case["known"])
    assert claim == Claim.from_messages(_messages(case), case["known"])
    assert claim.provider == "grimm-tales.andlo" and claim.provider_via == "the reading pipeline"


def test_dual_emitted_speech_counted_once():
    claim = Claim.from_messages([
        {"type": "speak", "data": {"utterance": "hi"}},
        {"type": "ovos.utterance.speak", "data": {"utterance": "hi"}}])
    assert claim.spoke == ["hi"]
    # the same sentence again under the same name is said twice
    claim = Claim.from_messages([{"type": "speak", "data": {"utterance": "hi"}},
                                 {"type": "speak", "data": {"utterance": "hi"}}])
    assert claim.spoke == ["hi", "hi"]


def test_in_session_keeps_sessionless():
    msgs = [{"type": "a", "context": {"session": {"session_id": "s1"}}},
            {"type": "b", "context": {"session": {"session_id": "s2"}}},
            {"type": "c"}]
    assert [m["type"] for m in in_session(msgs, "s1")] == ["a", "c"]


@pytest.mark.parametrize("a,b", [
    ("x.y:CancelAlert", "x.y:cancel_alert"),
    ("x.y:what.time.is.it.intent", "x.y:what_time_is_it"),
    ("WhatDay.intent", "x.y:what_day"),
    ("x.y:hello-world", "x.y:hello_world"),
])
def test_normalize(a, b):
    assert normalize_intent(a, "x.y") == normalize_intent(b, "x.y")


def test_awaiting_provider():
    claim = Claim.from_messages([{"type": "ovos.common_reading.search"}])
    assert claim.awaiting_provider
    claim.observe({"type": "ovos.common_reading.fetch_content.a.b"})
    assert not claim.awaiting_provider
