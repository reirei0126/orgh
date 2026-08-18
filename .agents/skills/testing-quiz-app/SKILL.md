---
name: testing-quiz-app
description: How to run and end-to-end test the static orgh spec-quiz web app in docs/quiz (no build, no server, localStorage-backed).
---

# Testing docs/quiz (orgh 仕様理解度クイズ)

## Running it
- Dependency-free static app. Open directly:
  `google-chrome --no-first-run file:///<repo>/docs/quiz/index.html`
- localStorage **works under file://** in Chrome for Testing on this box (verified), so no
  `python3 -m http.server` is needed. Use a local server only if a future Chrome blocks file:// storage.
- Maximize before recording: `wmctrl -a "orgh 仕様理解度クイズ" && wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`.

## Making assertions deterministic
The question bank (`docs/quiz/questions.js`, `window.ORGH_QUIZ`) is plain JS. Enumerate it with node
to pick a tiny, predictable pool before testing:

```
node -e "global.window={};require('./questions.js');var B=window.ORGH_QUIZ;
B.questions.forEach(q=>console.log(q.id,q.category,q.difficulty,q.type,q.answer))"
```

Useful facts (as of the initial bank, 77 q / 11 categories):
- In the raw bank every `answer` starts at index 0, but the app shuffles choices per question
  (`shuffleChoices()` in quiz.js, applied in `pick()` and on 間違えた設問だけ再挑戦). **Never assert on choice
  position — always match the correct answer by TEXT** taken from questions.js, and verify at least once
  that the displayed order differs from the bank order.
- Category `budget` = 5 single-choice questions → a good deterministic exam-mode pool.
- Category `desktop` + difficulty `applied` = exactly 1 `multi` question → ideal for testing
  order-independence and partial-selection grading in isolation.

## Reading persisted state
The store lives in localStorage key `orgh-quiz-v1` (`{runs:[], wrong:{id:count}}`). The
`browser_console` tool may attach to a different Chrome window/tab (e.g. the new-tab page) and read the
wrong origin's storage — closing other Chrome windows can also drop the CDP connection. A reliable
out-of-band read:

```
strings "$HOME/.config/google-chrome-for-testing/Default/Local Storage/leveldb/"*.log | grep -o '{"runs".\{0,400\}' | tail -1
```

Prefer UI evidence (reload → 直近の記録 list) as the primary proof; use the leveldb dump only to confirm
key name / wrong-counters.

## Weak-first ordering test recipe
Answer a known subset wrong in one session (`wrong[id]` becomes 1), return to setup, keep the same
category, set 出題数 to the number of missed questions, tick 苦手優先, start — the served questions must be
exactly the previously-missed ones.

## Regression checks worth repeating after changes
- 出題数 restore: a `wantedCount` variable remembers the user's desired count and `updatePoolSize()` sets
  `count.value = min(wantedCount, max(pool,1))`. Repro to re-check: load (10) → 全解除 (shows 1) → click one
  small category → the field must show min(10, pool), and a user-typed value must survive the round trip.
  This was broken once (stuck at 1) and is easy to regress.
- Result/復習 must render the same choice ordering the user saw: `finish()` builds its id→question map from
  `session.questions` (shuffled variants), not from the raw bank. If it regresses to the bank, あなたの回答 and
  正解 will show plausible-but-wrong text, so always cross-check those strings against what was on screen.
- Console baseline: 0 errors / 0 warnings; a11y Issues should be ~2 ("No label associated with a form
  field"), not ~16 — a jump back to 16 means the chip `name`/`aria-label` attributes were lost.

## Devin Secrets Needed
None — the app has no backend, credentials, or network calls.
