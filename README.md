# Triviador

## Question bank

Load the initial Bulgarian question bank with:

```bash
python backend/manage.py loaddata questions/question_bank.json
```

## M04: Territories and map

The project map is defined in `backend/games/map_definition.py` as a dictionary
of territory names to neighbor names. It contains 18 territories, and every
logical edge is intentionally present in both directions in that dictionary
and in the `Territory.neighbors` relation.

The map is:

- Скали: Дунавия, Житно поле
- Дунавия: Скали, Житно поле, Левента
- Житно поле: Скали, Дунавия, Левента, Балкания
- Левента: Дунавия, Житно поле, Балкания, Царево
- Балкания: Житно поле, Левента, Царево, Мадара, Средец
- Царево: Левента, Балкания, Мадара, Калиакра
- Мадара: Балкания, Царево, Калиакра, Пеликания
- Пеликания: Мадара, Калиакра, Средец, Езера
- Калиакра: Царево, Мадара, Пеликания
- Средец: Балкания, Пеликания, Езера, Пирина
- Езера: Пеликания, Средец, Пирина, Розова долина
- Пирина: Средец, Езера, Розова долина, Чуден край
- Розова долина: Езера, Пирина, Чуден край, Златен грозд
- Чуден край: Пирина, Розова долина, Златен грозд, Кукери
- Златен грозд: Розова долина, Чуден край, Кукери, Каракачан
- Кукери: Чуден край, Златен грозд, Каракачан, Слънчево
- Каракачан: Златен грозд, Кукери, Слънчево
- Слънчево: Кукери, Каракачан

Names are trimmed and compared case-sensitively. Slugs are trimmed and
lowercased, may contain Unicode letters, digits, underscores and hyphens, and
are unique per game. `validate_project_map()` checks the static definition;
`validate_game_map(game)` checks a complete game's names, slugs and edges
without creating or changing records. A valid example set of capitals is
Скали, Езера and Слънчево.

`Territory` records belong to one `Game`; owners are `GamePlayer` records from
that game. `Capital` uses one-to-one relations to both a territory and a
player, and requires the territory owner to be that player. Score and health
are constrained by the database; health 0 is retained as a destroyed capital.
Game deletion cascades to territories, while an owned territory and capital
are protected from deletion. The supported write entry points are model
validation and `Territory.set_neighbors()`; direct ORM/SQL mutation is not a
public input interface. A missing capital is represented by the absence of
the related object and is never created by a read.

The admin lists territories and capitals but cannot add or delete them or
edit their structural fields and relationships. Territory score and capital
health remain editable and are validated by the models.

## M05: Game initialization

The explicit backend operation is `games.services.initialize_game(game_id)`.
It returns `InitializationResult` on success and raises
`GameInitializationError` on refusal; its `code` identifies the reason:
`game_not_found`, `invalid_status`, `invalid_players`, `existing_state`,
`no_capital_triple`, or `concurrent_access`.

The operation locks the waiting game with `select_for_update()` and runs in one
`transaction.atomic()` block. It validates the project map and players before
creating anything, creates all territories and symmetric edges, chooses a
random valid triple from all pairwise non-neighboring triples, randomly assigns
it to the three active players, creates capitals with health 3, and changes
the status to `active` last. Any error rolls back the current attempt; a
pre-existing partial state is refused and is not repaired. Rounds are not
created or changed.

The database is SQLite in development (`backend/db.sqlite3`). SQLite provides
transaction rollback, but its locking is database-wide and
`select_for_update()` does not provide PostgreSQL-style row locks. A concurrent
write may therefore be refused with `concurrent_access`; no partial attempt is
committed. On a database with row-lock support, the game row lock ensures at
most one successful initialization. The Game admin cannot edit status or
timestamps, and GamePlayer admin changes are refused after activation.

## M06: Rounds

### Operations

All operations live in `backend/games/rounds.py`, run in one
`transaction.atomic()` block, lock the game row and require an `active` game:

| Operation | Effect |
|---|---|
| `create_city_capture_round(game_id)` | number = highest + 1, three participants, a random unused valid `NumericQuestion` stored as question 1, status `pending` (no deadline yet) |
| `start_round(round_id)` | `pending` → `active`, question 1 gets `started_at` and `deadline = started_at + 10 s` |
| `submit_answer(round_id, player_id, value)` | records one answer of a participant of the active question |
| `advance_round(round_id)` | after all answers or at/after the deadline: ranks the question, then creates the follow-up question or completes the round |
| `get_round_state(round_id)` | read-only: current question, deadline, `remaining_seconds`, all questions/answers and the stored ranking |

`Game.get_current_round()` returns the round with the highest number.

Time is read from `games.clock.now()` when the attempt is processed, before
the deadline check; the same value is stored as `submitted_at` and used for
speed. An answer is accepted only while `now < deadline` (refused exactly at
the deadline). Caller-supplied timestamps are never accepted; tests patch
`games.clock.now` instead of waiting. A numeric answer must be an `int` or a
string of digits (`3.5`, `"3.5"`, `4.0`, `True` are refused, never truncated).
A refused attempt does not use the player's answer.

### Errors

Every refusal raises a subclass of `games.errors.GameOperationError` (a
`ValidationError`) with a stable `code`; nothing is saved:

* `InvalidInputError` - wrong arguments: `invalid_id`, `invalid_value`,
  `player_not_in_game`, `not_a_participant`, `option_not_in_question`,
  `territory_not_in_game`, `territory_not_adjacent`, `own_territory`, ...
* `InvalidStateError` - not allowed now: `game_not_active`, `round_not_active`,
  `round_not_pending`, `round_completed`, `deadline_passed`, `already_answered`,
  `question_still_open`, `unfinished_round`, `question_bank_exhausted`,
  `concurrent_access`, ...
* `RecordNotFoundError` - `game_not_found`, `round_not_found`,
  `player_not_found`, `territory_not_found`, `option_not_found`.

```python
try:
    rounds.submit_answer(round_id, player_id, 42)
except InvalidStateError as exc:
    exc.code  # 'deadline_passed'
```

### Ranking

A better answer has the smaller absolute deviation; equal deviation is decided
by the earlier `submitted_at` (also when the answers lie on opposite sides).
Sorting uses `(deviation, submitted_at)` only, so the result does not depend
on record order. `required_places` is fixed at creation (2 when at least three
territories are free, otherwise 1).

Each question decides the places `first_place..last_place` for its own group.
Places are assigned in order; a group of answers with identical deviation and
time that covers a needed place stops the assignment and becomes the group of
a new numeric question (with a new 10-second deadline from its activation, in
the same round). Places assigned earlier are kept. No answer at all → a new
question for the same group. If a group has fewer answers than places, only
the highest places are filled; nobody outside the group is promoted.

After each question the result is checked first; a result decided on the third
question is valid. Otherwise a new question is created only if fewer than three
were asked and the bank has one; closing the previous question and creating the
next happen in one transaction. When the result stays incomplete the round is
completed with `outcome_reason`:

* `limit_reached` - a fourth question would be needed (takes precedence),
* `bank_exhausted` - no unused question for the follow-up,
* `insufficient_answers` - not enough accepted answers to fill every place.

`completed` without a winner is allowed only with one of these reasons (model
validation and a database check constraint). With a winner, a reason only
explains the incomplete second place.

### Data decision

**Chosen:** a round owns an ordered list of `RoundQuestion` rows
(`sequence` 1-3). Each stores the bank question through one of two typed
foreign keys, a snapshot of its text, correct answer / options, its group
(`participants`), the places it decides and its own `started_at`/`deadline`.
`RoundAnswer` points to one `RoundQuestion`. `RoundParticipant.place` and
`decided_by` hold the ranking. The snapshot means later bank edits do not
change what was asked or how it was scored; nothing is overwritten by a
follow-up question.

**Rejected:** keeping the question foreign keys on `Round` (the M02 design). It
allows only one question per round, so tie-break questions would overwrite the
asked question and its answers, and deadlines could not differ per question.

Migration `0005_rounds_lifecycle` replaces the M02 round fields. Rounds created
before it (possible only through the admin) are deleted by the migration
because they have no lifecycle data.

### Concurrency (single accepted answer)

The answer is checked in the transaction and the database enforces
`UniqueConstraint(question, player)`. If two attempts pass the check together,
the second insert fails and is reported as `already_answered`. On SQLite the
write lock serializes the transactions (a busy database is reported as
`concurrent_access`); on PostgreSQL the same constraint gives the guarantee.
Other invariants enforced by the database: one unfinished round per game,
unique `(round, sequence)`, a bank question at most once per game per model,
and closing a question is a compare-and-set update (`status='active'` →
`completed`), so two simultaneous `advance_round` calls create at most one
follow-up.

## M07: Territory capture and scoring

`backend/games/capture.py`:

* When a `city_capture` round completes with a winner, `CaptureRight` rows are
  created in the same transaction as the ranking and the win reward:

  | Free at creation | First | Second (if determined) |
  |---|---|---|
  | 3 or more | 2 | 1 |
  | 2 | 2 | 0 |
  | 1 | 1 | 0 |

* `capture_territory(game_id, player_id, territory_id)` - one atomic pick:
  sets the owner, raises `Territory.score`, awards capture points, records a
  `ScoreEvent` and uses one right. The first must use all rights before the
  second (`not_your_turn`); third players, exhausted rights and anything not
  from the last completed `city_capture` give `no_capture_rights`.
* The target must be free, of the same game and adjacent to a territory the
  player owns (capital included, recomputed after every pick). Only if no free
  territory borders the player may any free territory be chosen.
* `next_capture_right(game)`, `eligible_territories(game, player)`,
  `is_conquest_over(game)` are read helpers.

A new round is refused while a round is unfinished (`unfinished_round`) or a
right is unused (`pending_capture_rights`). A new `city_capture` needs at least
one free territory (`map_full`). A round without a winner gives no rights or
points.

The rights and the territory owner are changed with compare-and-set updates
(`used = old_used`, `owner IS NULL`), so of two concurrent attempts for the
same free territory or the last right only one succeeds.

### Scoring

Implemented in `backend/games/scoring.py` (system A):

* **Win reward:** `WIN_REWARD = 100` to the round winner (first place in
  `city_capture`, the winner of a battle or capital attack), once per round
  (unique constraint on `ScoreEvent`).
* **Territory increment:** each capture adds `TERRITORY_INCREMENT = 100` to
  `Territory.score` (also the first one, from 0).
* **Capture points:** the territory score **after** the increment, once per
  territory and round.

Every change is stored in `ScoreEvent` with player/territory scores before and
after and the calculation text. Scores never decrease.

Two systems applied to the same sequence (R1: A first, B second; A takes two
free territories, B one. R2: B first, C second; B takes two, C one. Battle: A
wins against B's territory with score 100):

| Step | System A (chosen) | System B (flat, rejected) |
|---|---|---|
| R1 win / ranking | A +100 | A +300, B +100 |
| R1 picks | A +100 +100, B +100 | A +50 +50, B +50 |
| R2 win / ranking | B +100 | B +300, C +100 |
| R2 picks | B +100 +100, C +100 | B +50 +50, C +50 |
| Battle | A +100 win + 200 capture | A +300 win + 50 capture |
| **Total A / B / C** | **600 / 400 / 100** | **750 / 550 / 150** |

System B pays ranking points and a flat 50 per capture, so the place in the
question dominates and the capture itself is worth little. System A pays the
first a single win reward and gives every territory value: the second place is
rewarded only through what it actually captures, and conquering a territory
that was captured before is worth more because its score has grown.

### Example (local records, `python manage.py demo_game`)

```
Round 1 (city_capture), free=15, ... = 10
  demo_boris: 12 (deviation 2)  demo_vera: 1 (deviation 9)  demo_ana: 50 (deviation 40)
  pick #1 demo_boris -> Балкания: territory 0 + 100 = 100; player 100 + 100 = 200
  pick #1 demo_boris -> Житно поле: territory 0 + 100 = 100; player 200 + 100 = 300
  pick #2 demo_vera -> Златен грозд: territory 0 + 100 = 100; player 0 + 100 = 100
...
Round 5 (city_capture), free=3
  pick #1 demo_vera -> Мадара (no free neighbour: any free territory)
```

The last incomplete package works the same way: with 2 free territories
`required_places` is 1 and the first receives 2 rights; with 1 free territory
the first receives 1 right (tests `test_last_two_territories_go_to_the_first`,
`test_last_single_territory`).

## M08: Battles

`rounds.create_battle_round(game_id, attacker_id, territory_id, defender_id=None)`
requires a full map, no unfinished round and no unused rights. The target must
belong to the game, be owned by another player and border a territory of the
attacker (no free-territory exception). Its owner is the defender; a different
`defender_id` is refused (`defender_mismatch`). A capital target gives
`capital_attack`, any other target `battle`. The round stores attacker,
defender and target; the first question is a random unused valid
`ChoiceQuestion` (four options, exactly one correct).

Start, the 10-second window, single answer and `advance_round` are shared with
`city_capture`. A choice answer is an `AnswerOption` id that must belong to the
asked question (`option_not_in_question` otherwise, even if the option exists).
Correctness is taken from the snapshot stored with the question.

| Correct answers | Next |
|---|---|
| One | its author wins |
| Two | new unused `NumericQuestion` for both (speed of the choice answers is ignored) |
| Zero | new unused `ChoiceQuestion` for both (a wrong answer is no better than none) |

After a numeric question only first place is needed; ties or no answers give
another numeric question for the tied group / same group. The limit of three
questions and the reasons `limit_reached` (precedence) / `bank_exhausted` are
the same as in M06.

Consequences, applied atomically with the completion:

* **Attack won (`battle`):** target owner → attacker, `Territory.score` +100,
  attacker gets 100 + the new territory score.
* **Defence won:** defender gets 100; owner and territory score unchanged.
* **`capital_attack`:** winner gets 100; capital, owner, territory and health
  unchanged.
* **No winner:** nothing changes.

Before applying, the target owner (and for capitals the capital) must still
match the battle; otherwise `advance_round` is refused with `target_changed`,
nothing is applied and earlier answers stay stored. A completed round cannot
be completed again.

### Representation of the two question types

`RoundQuestion` keeps two typed nullable foreign keys (`choice_question`,
`numeric_question`) with a check constraint that exactly one matches
`question_type`, and per-model unique constraints `(game, choice_question)` and
`(game, numeric_question)`. A `GenericForeignKey` was rejected: it has no
database foreign key, `PROTECT` or per-model uniqueness. Answers point to the
`RoundQuestion` row, never to a bank id, so `ChoiceQuestion(500)` and
`NumericQuestion(500)` in the same round are two different steps (test
`test_same_ids_in_both_models_stay_distinct`): the history reads
`[(choice, 500), (numeric, 500)]` and each answer belongs to exactly one step.

Demo (local records):

```
Round 6 (battle): demo_ana attacks Балкания (score 100) of demo_boris
  Q1 choice (bank id 11): both correct
  Q2 numeric (bank id 7) = 2007: demo_ana 2008 (deviation 1), demo_boris 2001 (deviation 6)
  winner demo_ana; Балкания owner demo_ana, score 200
    round_win demo_ana: battle win: 500 + 100 = 600
    capture demo_ana: territory 100 + 100 = 200; player 600 + 200 = 800
```

Two simultaneous attempts to create the numeric question after a tie both try
the compare-and-set close of the choice question; only one changes it, and
`UniqueConstraint(round, sequence)` allows only one question 2.
