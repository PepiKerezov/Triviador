"""M07: capture rights after a city_capture round and territory picks."""

from dataclasses import dataclass

from django.db.models import F

from . import scoring
from .errors import InvalidInputError, InvalidStateError
from .models import CITY_CAPTURE, ROUND_COMPLETED, CaptureRight, Territory
from .operations import atomic_operation, get_player, get_territory, lock_active_game


@dataclass(frozen=True)
class CaptureResult:
	territory_id: int
	player_id: int
	points: int
	player_score: int
	territory_score: int
	remaining_rights: int


def rights_for_free_count(free_count, second_determined):
	"""(first, second) pick rights for the free territories counted at creation."""
	first = min(2, free_count)
	second = 1 if free_count >= 3 and second_determined else 0
	return first, second


def grant_capture_rights(round_obj, first, second):
	"""Create the pick rights for a completed city_capture (once, atomically)."""
	first_allowed, second_allowed = rights_for_free_count(
		round_obj.free_territories_at_creation, second is not None
	)
	CaptureRight.objects.create(round=round_obj, player=first, order=1, allowed=first_allowed)
	if second_allowed:
		CaptureRight.objects.create(round=round_obj, player=second, order=2, allowed=second_allowed)


def has_pending_capture_rights(game):
	return CaptureRight.objects.filter(round__game=game, used__lt=F('allowed')).exists()


def next_capture_right(game):
	"""The right whose holder must pick next, or None."""
	return (
		CaptureRight.objects.filter(round__game=game, used__lt=F('allowed'))
		.select_related('player')
		.order_by('round__number', 'order')
		.first()
	)


def eligible_territories(game, player):
	"""Free territories the player may pick right now.

	Free territories adjacent to any territory the player owns (the capital
	included). If there is none, any free territory of the game.
	"""
	free = Territory.objects.filter(game=game, owner__isnull=True)
	adjacent = free.filter(neighbors__owner=player).distinct()
	return adjacent if adjacent.exists() else free


def is_conquest_over(game):
	return not Territory.objects.filter(game=game, owner__isnull=True).exists()


@atomic_operation
def capture_territory(game_id, player_id, territory_id):
	"""Use one capture right of ``player_id`` to take ``territory_id``.

	Changes the owner, raises the territory score, awards capture points and
	uses one right - all or nothing.
	"""
	game = lock_active_game(game_id)
	player = get_player(game, player_id)
	territory = get_territory(game, territory_id)

	last_round = game.get_current_round()
	if last_round is None or last_round.kind != CITY_CAPTURE or last_round.status != ROUND_COMPLETED:
		raise InvalidStateError('There are no capture rights to use.', 'no_capture_rights')
	rights = list(last_round.capture_rights.select_for_update().order_by('order'))
	current = next((right for right in rights if right.used < right.allowed), None)
	mine = next((right for right in rights if right.player_id == player.pk), None)
	if mine is None or mine.used >= mine.allowed:
		raise InvalidStateError('This player has no capture right left.', 'no_capture_rights')
	if current.pk != mine.pk:
		raise InvalidStateError('Another player must pick first.', 'not_your_turn')
	if territory.owner_id is not None:
		raise InvalidStateError('The territory is already taken.', 'territory_taken')
	if not eligible_territories(game, player).filter(pk=territory.pk).exists():
		raise InvalidInputError(
			'The territory is not adjacent to any territory of this player.', 'territory_not_adjacent'
		)

	used = CaptureRight.objects.filter(pk=mine.pk, used=mine.used).update(used=F('used') + 1)
	if used != 1:
		raise InvalidStateError('The capture right was used concurrently.', 'concurrent_access')
	event = scoring.capture(last_round, player, territory.pk, require_free=True)
	if event is None:
		raise InvalidStateError('The territory is already taken.', 'territory_taken')

	return CaptureResult(
		territory_id=territory.pk,
		player_id=player.pk,
		points=event.points,
		player_score=event.player_score_after,
		territory_score=event.territory_score_after,
		remaining_rights=mine.allowed - mine.used - 1,
	)
