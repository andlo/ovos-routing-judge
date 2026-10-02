"""Who took an utterance, and was it the skill that should have?

One judge for every tool that replays golden utterances against OVOS and
asks "did this sentence reach the right skill": a store's CI on an
in-process MiniCroft, ovos-tui-client on a live device over the
messagebus. Pure functions over the bus messages of ONE session - no
transport, no UI, no store knowledge - so the same row gets the same
verdict wherever it runs.

    from ovos_routing_judge import Claim, judge

    claim = Claim.from_messages(messages, known_ids={"ovos-skill-weather.openvoiceos"})
    verdict = judge(claim, own_ids={"ovos-skill-weather.openvoiceos"},
                    expected="ovos-skill-weather.openvoiceos:current_weather")
    verdict.kind   # "hit", "wrong_intent", "captured", "other", "unhandled", "hang"

Messages can be ovos_bus_client Message objects (msg_type, data,
context) or plain dicts ({"type" or "msg_type", "data", "context"}).
"""
from ovos_routing_judge.claim import (Claim, Signal, in_session, message_parts,
                                      session_of)
from ovos_routing_judge.judge import (CAPTURED, HANG, HIT, KINDS, OTHER, UNHANDLED,
                                      WRONG_INTENT, Verdict, intent_matches, judge,
                                      normalize_intent)
from ovos_routing_judge.version import __version__

__all__ = ["Claim", "Signal", "Verdict", "judge", "normalize_intent", "intent_matches",
           "in_session", "session_of", "message_parts",
           "HIT", "WRONG_INTENT", "CAPTURED", "OTHER", "UNHANDLED", "HANG", "KINDS",
           "__version__"]
