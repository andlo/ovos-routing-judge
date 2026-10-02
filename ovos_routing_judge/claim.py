"""Folding one session's bus messages into a Claim: who took the utterance.

Merged from the two judges this replaces (andlo/ovos-klondike-mercantile
scripts/compat/route.py and andlo/ovos-tui-client scripts.py, see
ovos-klondike-mercantile#48): every signal either of them accepted.

Signals come in tiers. The taker is the first known skill in the best
tier, so a skill that only speaks never beats one an intent was
dispatched to:

  INTENT    an intent dispatched to it (`<id>:<intent>`), ovos.intent.matched,
            or its pending get_response/converse capturing the utterance
  PROVIDER  a pipeline plugin asked it for content (common-reading fetch)
  OCP       OCP picked its result (play, or search.populate without a player)
  SKILL     handler start, a fallback that answered, common query's answer
  SPEAK     it spoke in this session

`ovos.intent.unmatched` means nobody, whatever else was seen.

With a session id, messages of other sessions are ignored, and a message
without a session can still show an intent, provider or OCP pick, but not
a SKILL or SPEAK claim: background activity of unrelated skills (a
scheduled event's handler, a fallback probe's reply) lands in the same
window without a session, and reading that as a claim gave false
cross-skill theft in ovos-test-harness's fleet suite.
"""
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Tuple

INTENT, PROVIDER, OCP, SKILL, SPEAK = range(5)
TIER_NAMES = ("intent", "provider", "ocp", "skill", "speak")

UNMATCHED = "ovos.intent.unmatched"
FAILURES = ("intent_failure", "complete_intent_failure")
SPEAK_TYPES = ("speak", "ovos.utterance.speak")
FALLBACK_PREFIX = "ovos.skills.fallback."
READING_SEARCH = "ovos.common_reading.search"
READING_FETCH_PREFIX = "ovos.common_reading.fetch_content."
OCP_PLAY = "ovos.common_play.play"
OCP_POPULATE = "ovos.common_play.search.populate"
OCP_ID = "ovos.common_play"
OCP_FIRED = "ocp:play"
# Message types with a colon that are never "<skill_id>:<intent>".
_NON_INTENT_PREFIXES = ("mycroft.", "ovos.common_play", "recognizer_loop", "ovos.utterance")
_COLON_TYPES_NOT_SKILLS = ("ocp", "question", "recognizer_loop", "skill", "mycroft")


def message_parts(msg: Any) -> Tuple[str, dict, dict]:
    """(msg_type, data, context) of a Message or a dict."""
    if isinstance(msg, dict):
        return (str(msg.get("msg_type") or msg.get("type") or ""),
                msg.get("data") or {}, msg.get("context") or {})
    return (str(getattr(msg, "msg_type", "") or ""),
            getattr(msg, "data", None) or {}, getattr(msg, "context", None) or {})


def session_of(msg: Any) -> str:
    sess = message_parts(msg)[2].get("session") or {}
    return (sess.get("session_id") or "") if isinstance(sess, dict) else ""


def in_session(messages: Iterable[Any], session_id: str) -> list:
    """The messages of one session, plus those without a session (older
    cores leave it off some messages). Judge only these: anything a
    previous row left running speaks in ITS session."""
    return [m for m in messages if session_of(m) in ("", session_id)]


def looks_like_component_id(prefix: str) -> bool:
    """'<name>.<author>' ids that aren't installed skills but still
    dispatch '<id>:<intent>' - pipeline plugins like
    'ovos-common-reading-pipeline-plugin.andlo:read_content'."""
    return ("." in prefix and " " not in prefix and "/" not in prefix
            and not prefix.startswith(_NON_INTENT_PREFIXES))


def ocp_pick(data: dict) -> Optional[str]:
    """skill_id of the track OCP picked: play's media, or the first entry
    of a play/populate tracks or playlist list."""
    media = data.get("media")
    if isinstance(media, dict) and media.get("skill_id"):
        return media["skill_id"]
    tracks = data.get("tracks") or data.get("playlist") or []
    first = tracks[0] if isinstance(tracks, list) and tracks else None
    if isinstance(first, dict):
        return first.get("skill_id")
    return getattr(first, "skill_id", None)


@dataclass(frozen=True)
class Signal:
    tier: int
    skill_id: str
    topic: str = ""       # what fired, "<skill_id>:<intent>", or "" for none
    source: str = ""      # the message type it came from


@dataclass
class Claim:
    signals: List[Signal] = field(default_factory=list)
    unmatched: bool = False          # ovos.intent.unmatched: nobody
    failed: bool = False             # intent_failure / complete_intent_failure seen
    captured_by: Optional[str] = None  # a pending get_response/converse took it
    ocp: bool = False                # OCP's pipeline took it (an ocp:* topic)
    provider: str = ""               # the skill a pipeline plugin or OCP got it from
    provider_via: str = ""           # "the reading pipeline" or "OCP"
    awaiting_provider: bool = False  # a search went out, no provider yet
    spoke: List[str] = field(default_factory=list)
    session_id: Optional[str] = None  # judge only this session (see module notes)
    count: int = 0                   # messages folded in
    _last_speak_type: str = ""
    _sessionless: bool = False

    @classmethod
    def from_messages(cls, messages: Iterable[Any], known_ids: Iterable[str] = (),
                      session_id: Optional[str] = None) -> "Claim":
        claim, known = cls(session_id=session_id), set(known_ids)
        for m in messages:
            claim.observe(m, known)
        return claim

    # ---------------------------------------------------------------- folding

    def _add(self, tier, skill_id, topic="", source=""):
        if tier in (SKILL, SPEAK) and self._sessionless:
            return
        if skill_id:
            self.signals.append(Signal(tier, str(skill_id), topic, source))

    def observe(self, msg: Any, known_ids: Iterable[str] = ()) -> None:
        """Fold one message in. `known_ids` (loaded skill ids, plus the
        expected one) tells '<skill_id>:<intent>' apart from other
        colon-containing types."""
        msg_type, data, context = message_parts(msg)
        known = known_ids if isinstance(known_ids, (set, frozenset)) else set(known_ids)
        sid = session_of(msg)
        if self.session_id and sid and sid != self.session_id:
            return
        self._sessionless = bool(self.session_id) and not sid
        self.count += 1

        if msg_type == UNMATCHED:
            self.unmatched = True
            return
        if msg_type in FAILURES:
            self.failed = True
            return
        if msg_type == "ovos.intent.matched":
            name = data.get("intent_name") or data.get("intent_type") or data.get("match_type") or ""
            skill = data.get("skill_id") or context.get("skill_id")
            if name and ":" not in name and skill:
                name = f"{skill}:{name}"
            self._add(INTENT, skill or (name.split(":", 1)[0] if ":" in name else ""), name, msg_type)
            return
        if msg_type.startswith("ocp:"):
            # OCP's pipeline took it; which skill serves it comes with play/populate
            self.ocp = True
            if msg_type == OCP_FIRED:
                self.awaiting_provider = True
            return
        if msg_type in (OCP_PLAY, OCP_POPULATE):
            skill = ocp_pick(data)
            if skill and skill != OCP_ID:
                self._add(OCP, skill, OCP_FIRED, msg_type)
                if not self.provider:
                    self.provider, self.provider_via = skill, "OCP"
                self.awaiting_provider = False
            return
        if ".converse." in msg_type:
            owner, _, rest = msg_type.partition(".converse.")
            if owner in known or looks_like_component_id(owner):
                if self.captured_by is None:
                    self.captured_by = owner
                self._add(INTENT, owner, f"{owner}:converse.{rest}", msg_type)
            return
        if ":" in msg_type:
            prefix = msg_type.split(":", 1)[0]
            if prefix in known or (prefix not in _COLON_TYPES_NOT_SKILLS and looks_like_component_id(prefix)):
                self._add(INTENT, prefix, msg_type, msg_type)
            elif msg_type == "question:action":
                self._add(SKILL, data.get("skill_id"), "", msg_type)
            return
        if msg_type == "mycroft.skill.handler.start":
            name = str(data.get("name") or "")
            skill = context.get("skill_id") or data.get("skill_id") or (name.split(":", 1)[0] if ":" in name else "")
            self._add(SKILL, skill, name if ":" in name else "", msg_type)
        elif msg_type.startswith(FALLBACK_PREFIX) and msg_type.endswith(".response"):
            if data.get("result"):
                self._add(SKILL, msg_type[len(FALLBACK_PREFIX):-len(".response")], "", msg_type)
        elif msg_type == READING_SEARCH:
            self.awaiting_provider = True
        elif msg_type.startswith(READING_FETCH_PREFIX) and not msg_type.endswith(".response"):
            skill = msg_type[len(READING_FETCH_PREFIX):]
            self._add(PROVIDER, skill, "", msg_type)
            if not self.provider:
                self.provider, self.provider_via = skill, "the reading pipeline"
            self.awaiting_provider = False
        elif msg_type in SPEAK_TYPES:
            self._add(SPEAK, context.get("skill_id"), "", msg_type)
            # A dual-emitting core sends the same sentence under both names,
            # back to back - count it once.
            utterance = data.get("utterance")
            if utterance and not (self.spoke and self.spoke[-1] == utterance
                                  and self._last_speak_type != msg_type):
                self.spoke.append(utterance)
            self._last_speak_type = msg_type

    # ---------------------------------------------------------------- reading

    def taker(self, known_ids: Optional[Iterable[str]] = None) -> Optional[str]:
        """Who took the utterance: the first skill in the best tier. With
        `known_ids`, only those count (a pipeline plugin's own intent with
        no provider behind it is then nobody); without, anyone does."""
        if self.unmatched:
            return None
        known = None if known_ids is None else set(known_ids)
        for tier in (INTENT, PROVIDER, OCP, SKILL, SPEAK):
            for s in self.signals:
                if s.tier == tier and (known is None or s.skill_id in known):
                    return s.skill_id
        return None

    def tier_of(self, skill_id: str) -> Optional[str]:
        tiers = [s.tier for s in self.signals if s.skill_id == skill_id]
        return TIER_NAMES[min(tiers)] if tiers else None

    def fired(self, skill_id: str) -> List[str]:
        """What fired for this skill: its intent topics and handler names,
        plus 'ocp:play' when OCP handed it the utterance."""
        out = []
        for s in self.signals:
            if s.skill_id == skill_id and s.topic and s.topic not in out:
                out.append(s.topic)
        return out

    @property
    def handlers(self) -> List[str]:
        """Everyone that took part, in order of appearance."""
        out = []
        for s in self.signals:
            if s.skill_id not in out:
                out.append(s.skill_id)
        return out

    @property
    def intents(self) -> List[str]:
        out = []
        for s in self.signals:
            if s.tier == INTENT and s.topic and s.topic not in out:
                out.append(s.topic)
        return out

    @property
    def empty(self) -> bool:
        """Nothing happened at all: no signal, no unmatched, no failure."""
        return not (self.signals or self.unmatched or self.failed or self.ocp)


def is_converse_capture(topic: str) -> bool:
    return ":converse." in topic

