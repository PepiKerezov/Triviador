from django.contrib.auth import get_user_model
from django.test import TestCase

from games.map_definition import PROJECT_MAP
from games.models import ACTIVE, Capital, Game, GamePlayer, Territory
from games.services import GameInitializationError, initialize_game
from questions.models import Category, ChoiceQuestion


class GameInitializationTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.creator = get_user_model().objects.create_user(
			username='init_creator', email='init_creator@example.com', password='password'
		)
		cls.users = [
			get_user_model().objects.create_user(
				username=f'init_player_{index}',
				email=f'init_player_{index}@example.com',
				password='password',
			)
			for index in range(3)
		]
		cls.category = Category.objects.create(name='Initialization')
		cls.question = ChoiceQuestion.objects.create(
			category=cls.category,
			text='Initialization question',
		)

	def make_game(self, status='waiting', player_count=3):
		game = Game.objects.create(created_by=self.creator, status=status)
		for index, user in enumerate(self.users[:player_count], start=1):
			GamePlayer.objects.create(game=game, user=user, player_order=index)
		return game

	def test_initialization_creates_complete_map_and_three_non_neighboring_capitals(self):
		game = self.make_game()
		result = initialize_game(game.pk)

		game.refresh_from_db()
		self.assertEqual(result.territory_count, len(PROJECT_MAP))
		self.assertEqual(game.status, ACTIVE)
		self.assertEqual(game.territories.count(), len(PROJECT_MAP))
		self.assertEqual(Capital.objects.filter(territory__game=game).count(), 3)
		capitals = list(Capital.objects.filter(territory__game=game).select_related('territory'))
		self.assertTrue(all(capital.health == 3 for capital in capitals))
		self.assertEqual(game.territories.filter(owner__isnull=True).count(), len(PROJECT_MAP) - 3)
		self.assertEqual(game.territories.filter(score=0).count(), len(PROJECT_MAP))
		for first in capitals:
			for second in capitals:
				if first.id < second.id:
					self.assertNotIn(second.territory, first.territory.neighbors.all())

	def test_initialization_refuses_invalid_game_without_partial_data(self):
		game = self.make_game(player_count=2)

		with self.assertRaisesRegex(GameInitializationError, 'exactly three'):
			initialize_game(game.pk)

		self.assertEqual(game.territories.count(), 0)
		game.refresh_from_db()
		self.assertEqual(game.status, 'waiting')

	def test_initialization_refuses_partial_state_without_repairing_it(self):
		game = self.make_game()
		Territory.objects.create(game=game, name='Скали', slug='скали')

		with self.assertRaises(GameInitializationError) as error:
			initialize_game(game.pk)

		self.assertEqual(error.exception.code, 'existing_state')
		self.assertEqual(game.territories.count(), 1)
		game.refresh_from_db()
		self.assertEqual(game.status, 'waiting')

	def test_initialization_is_not_repeatable(self):
		game = self.make_game()
		initialize_game(game.pk)
		capital_ids = set(Capital.objects.values_list('id', flat=True))

		with self.assertRaisesRegex(GameInitializationError, 'waiting'):
			initialize_game(game.pk)

		self.assertEqual(set(Capital.objects.values_list('id', flat=True)), capital_ids)

	def test_initialization_does_not_change_existing_rounds(self):
		game = self.make_game()
		from games.models import Round

		round = Round.objects.create(
			game=game,
			number=1,
			status='pending',
			question_type='choice',
			choice_question=self.question,
		)
		initialize_game(game.pk)

		self.assertTrue(Round.objects.filter(pk=round.pk).exists())