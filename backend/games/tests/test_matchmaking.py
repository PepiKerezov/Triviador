from django.contrib.auth import get_user_model
from django.test import TestCase

from games.models import Game, GamePlayer, MatchmakingEntry
from games.services import form_matchmaking_game


class MatchmakingServiceTests(TestCase):
	def make_waiting_entries(self, count):
		users = [
			get_user_model().objects.create_user(
				username=f'player_{index}',
				email=f'player_{index}@example.com',
				password='password',
			)
			for index in range(count)
		]
		MatchmakingEntry.objects.bulk_create(
			[MatchmakingEntry(user=user) for user in users]
		)
		return users

	def test_two_waiting_players_do_not_change_database(self):
		self.make_waiting_entries(2)
		before = {
			'entries': MatchmakingEntry.objects.count(),
			'games': Game.objects.count(),
			'players': GamePlayer.objects.count(),
		}

		result = form_matchmaking_game()

		self.assertIsNone(result.game_id)
		self.assertEqual(result.selected_user_ids, ())
		self.assertEqual(
			{
				'entries': MatchmakingEntry.objects.count(),
				'games': Game.objects.count(),
				'players': GamePlayer.objects.count(),
			},
			before,
		)
