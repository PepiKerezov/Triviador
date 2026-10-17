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
