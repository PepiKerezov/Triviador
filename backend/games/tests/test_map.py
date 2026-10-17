from django.core.exceptions import ValidationError
from django.test import TestCase

from games.map_definition import PROJECT_MAP, validate_game_map, validate_project_map
from games.models import Capital, Game, GamePlayer, Territory
from django.contrib.auth import get_user_model


class MapDefinitionTests(TestCase):
	def test_project_map_is_valid_and_uses_bidirectional_neighbors(self):
		validate_project_map()
		self.assertEqual(len(PROJECT_MAP), 18)
		self.assertIn('Скали', PROJECT_MAP['Дунавия'])
		self.assertIn('Дунавия', PROJECT_MAP['Скали'])

	def test_game_map_validation_requires_exact_definition(self):
		user = get_user_model().objects.create_user(
			username='map_creator', email='map_creator@example.com', password='password'
		)
		game = Game.objects.create(created_by=user, status='waiting')
		territories = {
			name: Territory.objects.create(game=game, name=name, slug=name.lower().replace(' ', '-'))
			for name in PROJECT_MAP
		}
		for name, neighbors in PROJECT_MAP.items():
			territories[name].neighbors.set(territories[neighbor] for neighbor in neighbors)

		validate_game_map(game)
		territories['Скали'].neighbors.remove(territories['Дунавия'])
		with self.assertRaises(ValidationError):
			validate_game_map(game)


class TerritoryAndCapitalTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.creator = get_user_model().objects.create_user(
			username='territory_creator', email='territory_creator@example.com', password='password'
		)
		cls.player_user = get_user_model().objects.create_user(
			username='territory_player', email='territory_player@example.com', password='password'
		)
		cls.other_user = get_user_model().objects.create_user(
			username='territory_other', email='territory_other@example.com', password='password'
		)
		cls.game = Game.objects.create(created_by=cls.creator, status='waiting')
		cls.other_game = Game.objects.create(created_by=cls.creator, status='waiting')
		cls.player = GamePlayer.objects.create(game=cls.game, user=cls.player_user, player_order=1)
		cls.other_player = GamePlayer.objects.create(game=cls.other_game, user=cls.other_user, player_order=1)
		cls.territory = Territory.objects.create(game=cls.game, name='Скали', slug='скали')
		cls.other_territory = Territory.objects.create(game=cls.other_game, name='Скали', slug='скали')

	def test_territory_identity_is_unique_per_game_but_not_across_games(self):
		self.assertEqual(self.territory.name, self.other_territory.name)
		with self.assertRaises(ValidationError):
			Territory(game=self.game, name=' Скали ', slug='СКАЛИ').full_clean()

	def test_owner_and_capital_must_stay_in_same_game(self):
		with self.assertRaises(ValidationError):
			Territory(game=self.game, name='Дунавия', slug='дунавия', owner=self.other_player).full_clean()
		self.territory.owner = self.player
		self.territory.save()
		capital = Capital(territory=self.territory, player=self.player)
		capital.full_clean()
		capital.save()
		self.assertEqual(self.player.capital, capital)
		with self.assertRaises(ValidationError):
			Capital(territory=self.territory, player=self.other_player).full_clean()

	def test_neighbors_require_same_game_and_at_least_two(self):
		neighbor = Territory.objects.create(game=self.game, name='Дунавия', slug='дунавия')
		with self.assertRaises(ValidationError):
			self.territory.set_neighbors([neighbor])
		with self.assertRaises(ValidationError):
			self.territory.set_neighbors([neighbor, self.other_territory])