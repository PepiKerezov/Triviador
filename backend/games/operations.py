"""Shared helpers for the game operations (rounds, captures, battles)."""

import re
from functools import wraps

from django.db import IntegrityError, OperationalError, transaction

from .errors import GameOperationError, InvalidInputError, InvalidStateError, RecordNotFoundError
from .models import ACTIVE, Game, GamePlayer, Territory

MAX_NUMERIC_ANSWER = 10**15
_INTEGER_TEXT = re.compile(r'^[+-]?\d+$')


def atomic_operation(func):
	"""Run ``func`` in one transaction and translate database conflicts.

	A unique/check constraint violation or a database lock caused by a
	concurrent attempt becomes ``InvalidStateError('concurrent_access')``; the
	whole attempt is rolled back.
	"""

	@wraps(func)
	def wrapper(*args, **kwargs):
		try:
			with transaction.atomic():
				return func(*args, **kwargs)
		except GameOperationError:
			raise
		except (IntegrityError, OperationalError) as exc:
			raise InvalidStateError(
				'A concurrent change conflicted with this operation; nothing was saved.',
				'concurrent_access',
			) from exc

	return wrapper


def require_id(value, name):
	if isinstance(value, bool) or not isinstance(value, int) or value < 1:
		raise InvalidInputError(f'{name} must be a positive integer id.', 'invalid_id')
	return value


def parse_integer_answer(value):
	"""Accept an int or a string of digits; never truncate a fraction."""
	if isinstance(value, bool):
		raise InvalidInputError('The answer must be a whole number.', 'invalid_value')
	if isinstance(value, int):
		number = value
	elif isinstance(value, str) and _INTEGER_TEXT.match(value.strip()):
		number = int(value.strip())
	else:
		raise InvalidInputError('The answer must be a whole number.', 'invalid_value')
	if abs(number) > MAX_NUMERIC_ANSWER:
		raise InvalidInputError('The answer is out of range.', 'invalid_value')
	return number


def lock_active_game(game_id):
	require_id(game_id, 'game_id')
	game = Game.objects.select_for_update().filter(pk=game_id).first()
	if game is None:
		raise RecordNotFoundError('The game does not exist.', 'game_not_found')
	if game.status != ACTIVE:
		raise InvalidStateError('The game is not active.', 'game_not_active')
	return game


def get_player(game, player_id):
	require_id(player_id, 'player_id')
	player = GamePlayer.objects.filter(pk=player_id).first()
	if player is None:
		raise RecordNotFoundError('The player does not exist.', 'player_not_found')
	if player.game_id != game.pk or not player.is_active:
		raise InvalidInputError('The player is not an active player of this game.', 'player_not_in_game')
	return player


def get_territory(game, territory_id):
	require_id(territory_id, 'territory_id')
	territory = Territory.objects.filter(pk=territory_id).first()
	if territory is None:
		raise RecordNotFoundError('The territory does not exist.', 'territory_not_found')
	if territory.game_id != game.pk:
		raise InvalidInputError('The territory belongs to another game.', 'territory_not_in_game')
	return territory
