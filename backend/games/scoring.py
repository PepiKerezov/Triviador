"""Scoring rules (system A, see README "M07: Scoring").

* Winning a round (first place in city_capture, either side winning a battle,
  the winner of a capital attack) gives ``WIN_REWARD``.
* Every capture raises ``Territory.score`` by ``TERRITORY_INCREMENT`` and gives
  the capturing player the territory score *after* the increase.

Each change is recorded in ``ScoreEvent`` with the values before and after.
Database constraints allow one win reward per round and one capture reward per
territory and round, so a repeated attempt cannot double-count.
"""

from django.db.models import F

from .models import SCORE_CAPTURE, SCORE_ROUND_WIN, GamePlayer, ScoreEvent, Territory

WIN_REWARD = 100
TERRITORY_INCREMENT = 100


def _add_to_player(player_id, points):
	player = GamePlayer.objects.select_for_update().get(pk=player_id)
	before = player.score
	GamePlayer.objects.filter(pk=player_id).update(score=F('score') + points)
	return before, before + points


def award_round_win(round_obj, player):
	before, after = _add_to_player(player.pk, WIN_REWARD)
	return ScoreEvent.objects.create(
		game_id=round_obj.game_id,
		round=round_obj,
		player_id=player.pk,
		kind=SCORE_ROUND_WIN,
		points=WIN_REWARD,
		player_score_before=before,
		player_score_after=after,
		calculation=f'{round_obj.kind} win: {before} + {WIN_REWARD} = {after}',
	)


def capture(round_obj, player, territory_id, *, require_owner_id=None, require_free=False):
	"""Give ``territory_id`` to ``player`` and award the capture points.

	The ownership change is a compare-and-set update: it succeeds only if the
	territory is still free (``require_free``) or still owned by
	``require_owner_id``. Returns the ScoreEvent, or None if the territory no
	longer matches (the caller must then refuse and roll back).
	"""
	queryset = Territory.objects.filter(pk=territory_id, game_id=round_obj.game_id)
	if require_free:
		queryset = queryset.filter(owner__isnull=True)
	else:
		queryset = queryset.filter(owner_id=require_owner_id)
	territory = queryset.select_for_update().first()
	if territory is None:
		return None
	territory_before = territory.score
	changed = queryset.filter(score=territory_before).update(
		owner_id=player.pk, score=F('score') + TERRITORY_INCREMENT
	)
	if changed != 1:
		return None
	territory_after = territory_before + TERRITORY_INCREMENT
	points = territory_after
	before, after = _add_to_player(player.pk, points)
	return ScoreEvent.objects.create(
		game_id=round_obj.game_id,
		round=round_obj,
		player_id=player.pk,
		kind=SCORE_CAPTURE,
		territory_id=territory.pk,
		points=points,
		player_score_before=before,
		player_score_after=after,
		territory_score_before=territory_before,
		territory_score_after=territory_after,
		calculation=(
			f'territory {territory_before} + {TERRITORY_INCREMENT} = {territory_after}; '
			f'player {before} + {points} = {after}'
		),
	)
