# ovos-routing-judge

Who took an utterance, and was it the skill that should have?

One judge for every tool that replays golden utterances
(`test/end2end/golden_utterances_<lang>.jsonl`) against
[OpenVoiceOS](https://openvoiceos.org) and asks whether each sentence reached
the right skill. It is pure Python over the bus messages of **one session**:
no messagebus connection, no UI, no store knowledge, no dependencies. So the
same row gets the same verdict wherever it runs:

- [ovos-klondike-mercantile](https://github.com/andlo/ovos-klondike-mercantile)'s
  CI, on an in-process MiniCroft;
- [ovos-tui-client](https://github.com/andlo/ovos-tui-client)'s test runs
  (`ovos-tui --run`), on a live device over the messagebus.

A failure in CI can then be reproduced on a device and judged the same way
(andlo/ovos-klondike-mercantile#48).

## Use

```python
from ovos_routing_judge import Claim, in_session, judge

messages = in_session(recorded, session_id)        # Message objects or dicts
claim = Claim.from_messages(messages, known_ids=loaded_skill_ids)
v = judge(claim, own_ids={"ovos-skill-date-time.openvoiceos"},
          expected="ovos-skill-date-time.openvoiceos:what_time_is_it",
          hung=timed_out, known_ids=loaded_skill_ids)
v.kind     # hit | wrong_intent | captured | other | unhandled | hang
v.taker    # who took it
v.via      # its best signal: intent | provider | ocp | skill | speak
v.detail   # one line on what happened
```

`Claim.observe(message, known_ids)` folds messages in one at a time, for a
live run that wants to know as soon as something matched.

## Verdicts

| kind | meaning |
|---|---|
| `hit` | the row's skill took it (with the expected intent, when the row names one) |
| `wrong_intent` | the row's skill took it with another intent |
| `captured` | the row's skill was waiting for an answer (get_response / converse) and took the sentence as that answer |
| `other` | another skill took it (`taker`); a store can split this further |
| `unhandled` | nobody took it, or only a pipeline stage with no skill behind it |
| `hang` | nobody took it and the caller timed out |

## What counts as taking a sentence

Signals come in tiers; the taker is the first known skill in the best tier:

1. **intent**: `<skill_id>:<intent>` dispatched, `ovos.intent.matched`, or a
   pending `<skill_id>.converse.*` capturing it
2. **provider**: a pipeline plugin asked it for content
   (`ovos.common_reading.fetch_content.<skill_id>`)
3. **ocp**: OCP picked its result (`ovos.common_play.play` media, or the
   first track of `play` / `search.populate` without a player)
4. **skill**: handler start, a fallback that answered, common query's
   `question:action`
5. **speak**: it spoke in this session (`speak` or core 3's `ovos.utterance.speak`)

`ovos.intent.unmatched` means nobody, whatever else was seen.

Intent names are compared in one spelling: `Name.intent` (ovos-workshop 1.x)
vs `Name`, CamelCase in older releases vs snake_case, padatious
`what.time.is.it` vs padacioso `what_time_is_it`. A row with
`"intent_type": "ocp"` must go through OCP.

## The contract

`tests/fixtures/cases.json` holds recorded message sequences and the verdict
each must get. When a core changes its signals, a case goes in there and every
tool using the package gets the fix.

## License

Apache-2.0
