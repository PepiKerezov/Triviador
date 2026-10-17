import random
from dataclasses import dataclass
from itertools import combinations

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from .map_definition import PROJECT_MAP, slug_for_name, validate_project_map
from .models import ACTIVE, WAITING, Capital, Game, Territory


class GameInitializationError(ValidationError):
	"""A documented refusal to initialize a game."""


@dataclass(frozen=True)
class InitializationResult:
	game_id: int
	territory_count: int
	capital_count: int


def _refuse(message, code):
	raise GameInitializationError(message, code=code)


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