import random
from dataclasses import dataclass
from itertools import combinations

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from .map_definition import PROJECT_MAP, slug_for_name, validate_project_map
from .models import (
	ACTIVE,
	BLUE,
	GREEN,
	RED,
	WAITING,
	Capital,
	Game,
	GamePlayer,
	MatchmakingEntry,
	Territory,
)


class GameInitializationError(ValidationError):
	"""A documented refusal to initialize a game."""


@dataclass(frozen=True)
class InitializationResult:
	game_id: int
	territory_count: int
	capital_count: int


class MatchmakingError(ValidationError):
	"""A documented refusal to change matchmaking state."""


@dataclass(frozen=True)
class MatchmakingResult:
	game_id: int | None
	selected_user_ids: tuple[int, ...]


def _refuse(message, code):
	raise GameInitializationError(message, code=code)


def _matchmaking_refuse(message, code):
	raise MatchmakingError(message, code=code)


def _eligible_matchmaking_entries():
	return (
		MatchmakingEntry.objects
		.filter(
			~Q(
				user__game_players__game__status__in=(WAITING, ACTIVE)
			)
		)
		.distinct()
		.order_by('created_at', 'pk')
	)


def form_matchmaking_game():
	with transaction.atomic():
		entries = list(_eligible_matchmaking_entries().select_for_update())
		if len(entries) < 3:
			return MatchmakingResult(None, ())

		selected = random.SystemRandom().sample(entries, 3)
		game = Game.objects.create(created_by=selected[0].user, status=WAITING)
		GamePlayer.objects.bulk_create(
			[
				GamePlayer(
					game=game,
					user=entry.user,
					player_order=order,
					color=color,
					score=0,
				)
				for order, (entry, color) in enumerate(
					zip(selected, (RED, BLUE, GREEN)),
					start=1,
				)
			]
		)
		MatchmakingEntry.objects.filter(pk__in=[entry.pk for entry in selected]).delete()
		return MatchmakingResult(game.id, tuple(entry.user_id for entry in selected))


def join_matchmaking(user):
	with transaction.atomic():
		if MatchmakingEntry.objects.filter(user=user).exists():
			_matchmaking_refuse('The user is already waiting for a game.', 'already_waiting')
		if GamePlayer.objects.filter(
			user=user,
			game__status__in=(WAITING, ACTIVE),
		).exists():
			_matchmaking_refuse('The user is already participating in a game.', 'already_in_game')
		MatchmakingEntry.objects.create(user=user)
		return form_matchmaking_game()


def leave_matchmaking(user):
	with transaction.atomic():
		MatchmakingEntry.objects.filter(user=user).delete()


def _choose_capitals(territory_by_name):
	valid_triples = [
		triple
		for triple in combinations(PROJECT_MAP, 3)
		if all(
			second not in PROJECT_MAP[first]
			for first, second in combinations(triple, 2)
		)
	]
	if not valid_triples:
		_refuse('The project map has no valid capital triple.', 'no_capital_triple')
	triple = random.SystemRandom().choice(valid_triples)
	return [territory_by_name[name] for name in triple]


def initialize_game(game_id):
	try:
		with transaction.atomic():
			try:
				game = Game.objects.select_for_update().get(pk=game_id)
			except Game.DoesNotExist:
				_refuse('The game does not exist.', 'game_not_found')

			if game.status != WAITING:
				_refuse('Only waiting games can be initialized.', 'invalid_status')
			players = list(game.players.filter(is_active=True).order_by('player_order'))
			if len(players) != 3 or any(player.score < 0 for player in players):
				_refuse('The game must have exactly three valid active players.', 'invalid_players')
			if Territory.objects.filter(game=game).exists() or Capital.objects.filter(player__game=game).exists():
				_refuse('The game already has initialization data.', 'existing_state')

			validate_project_map()
			territory_by_name = {
				name: Territory.objects.create(game=game, name=name, slug=slug_for_name(name), score=0)
				for name in PROJECT_MAP
			}
			for name, neighbors in PROJECT_MAP.items():
				territory_by_name[name].set_neighbors(
					[territory_by_name[neighbor] for neighbor in neighbors]
				)

			capital_territories = _choose_capitals(territory_by_name)
			players = list(players)
			random.SystemRandom().shuffle(players)
			for player, territory in zip(players, capital_territories):
				territory.owner = player
				territory.save(update_fields=('owner', 'score'))
				Capital.objects.create(territory=territory, player=player, health=3)

			game.status = ACTIVE
			game.started_at = timezone.now()
			game.save(update_fields=('status', 'started_at'))
		return InitializationResult(game.id, len(territory_by_name), len(capital_territories))
	except DatabaseError as exc:
		raise GameInitializationError(
			'Initialization could not obtain the database lock.', code='concurrent_access'
		) from exc