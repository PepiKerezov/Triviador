from unittest import mock

from django.test import TestCase

from games import rounds
from games.capture import capture_territory, eligible_territories, is_conquest_over, next_capture_right
from games.errors import InvalidInputError, InvalidStateError
from games.models import QUESTION_ACTIVE, CaptureRight, ScoreEvent, Territory
from games.scoring import TERRITORY_INCREMENT, WIN_REWARD

from .helpers import GameTestMixin


class CaptureTestBase(GameTestMixin, TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.make_users('capture')
		cls.make_bank(numeric=12)

	def setUp(self):
		super().setUp()
		self.game, self.players = self.make_game()
		self.p1, self.p2, self.p3 = self.players
		# Capitals: p1 Скали, p2 Езера, p3 Слънчево.

	def play_round(self, ranking, answer_all=True):
		"""Play a city_capture round; ``ranking`` lists players best first."""
		round_obj = rounds.create_city_capture_round(self.game.pk)
		rounds.start_round(round_obj.pk)
		question = round_obj.questions.get(status=QUESTION_ACTIVE)
		for offset, player in enumerate(ranking):
			rounds.submit_answer(round_obj.pk, player.pk, question.correct_answer + offset)
		self.clock.advance(10)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		return round_obj

	def pick(self, player, name):
		return capture_territory(self.game.pk, player.pk, self.territory(self.game, name).pk)

	def score(self, player):
		player.refresh_from_db()
		return player.score

	def leave_free(self, names):
		"""Give every free territory except ``names`` to p3."""
		Territory.objects.filter(game=self.game, owner__isnull=True).exclude(name__in=names).update(
			owner=self.p3, score=100
		)


class DistributionTests(CaptureTestBase):
	def test_two_plus_one_in_order_with_scores(self):
		round_obj = self.play_round([self.p1, self.p2, self.p3])
		self.assertEqual(self.score(self.p1), WIN_REWARD)
		self.assertEqual(self.score(self.p2), 0)
		rights = {right.player_id: (right.order, right.allowed) for right in round_obj.capture_rights.all()}
		self.assertEqual(rights, {self.p1.pk: (1, 2), self.p2.pk: (2, 1)})

		with self.assertRaises(InvalidStateError) as caught:
			self.pick(self.p2, 'Пеликания')
		self.assertEqual(caught.exception.code, 'not_your_turn')

		# First capture from zero: territory 0 -> 100, p1 100 -> 200.
		result = self.pick(self.p1, 'Дунавия')
		self.assertEqual((result.territory_score, result.points, result.player_score), (100, 100, 200))
		event = ScoreEvent.objects.get(kind='capture', territory__name='Дунавия')
		self.assertEqual((event.player_score_before, event.player_score_after), (100, 200))
		self.assertEqual((event.territory_score_before, event.territory_score_after), (0, 100))

		# Левента borders only the just-captured Дунавия, not the capital.
		self.assertIn(self.territory(self.game, 'Левента'), eligible_territories(self.game, self.p1))
		self.pick(self.p1, 'Левента')
		self.assertEqual(self.score(self.p1), 300)

		with self.assertRaises(InvalidStateError) as caught:
			self.pick(self.p1, 'Житно поле')
		self.assertEqual(caught.exception.code, 'no_capture_rights')

		self.pick(self.p2, 'Пеликания')
		self.assertEqual(self.score(self.p2), TERRITORY_INCREMENT)
		self.assertEqual(self.score(self.p3), 0)
		self.assertIsNone(next_capture_right(self.game))

	def test_third_player_has_no_right(self):
		self.play_round([self.p1, self.p2, self.p3])
		with self.assertRaises(InvalidStateError) as caught:
			self.pick(self.p3, 'Кукери')
		self.assertEqual(caught.exception.code, 'no_capture_rights')

	def test_last_two_territories_go_to_the_first(self):
		self.leave_free(['Дунавия', 'Житно поле'])
		round_obj = self.play_round([self.p2, self.p1, self.p3])
		self.assertEqual(round_obj.required_places, 1)
		self.assertEqual(
			list(round_obj.capture_rights.values_list('player_id', 'allowed')), [(self.p2.pk, 2)]
		)
		# p2 (Езера) has no free neighbour: any free territory is allowed.
		self.pick(self.p2, 'Дунавия')
		self.pick(self.p2, 'Житно поле')
		self.assertTrue(is_conquest_over(self.game))
		with self.assertRaises(InvalidStateError) as caught:
			rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(caught.exception.code, 'map_full')

	def test_last_single_territory(self):
		self.leave_free(['Дунавия'])
		round_obj = self.play_round([self.p1, self.p2, self.p3])
		self.assertEqual(list(round_obj.capture_rights.values_list('allowed', flat=True)), [1])
		self.pick(self.p1, 'Дунавия')
		self.assertTrue(is_conquest_over(self.game))


class AdjacencyTests(CaptureTestBase):
	def test_non_adjacent_target_is_refused_without_using_a_right(self):
		self.play_round([self.p1, self.p2, self.p3])
		with self.assertRaises(InvalidInputError) as caught:
			self.pick(self.p1, 'Мадара')
		self.assertEqual(caught.exception.code, 'territory_not_adjacent')
		self.assertEqual(CaptureRight.objects.get(player=self.p1).used, 0)
		self.assertIsNone(self.territory(self.game, 'Мадара').owner)

	def test_any_free_territory_when_no_free_neighbour(self):
		self.set_owner(self.game, ['Дунавия', 'Житно поле'], self.p2)
		self.play_round([self.p1, self.p2, self.p3])
		self.pick(self.p1, 'Мадара')
		self.assertEqual(self.territory(self.game, 'Мадара').owner, self.p1)

	def test_exception_does_not_apply_with_a_free_neighbour(self):
		self.set_owner(self.game, ['Дунавия'], self.p2)
		self.play_round([self.p1, self.p2, self.p3])
		with self.assertRaises(InvalidInputError):
			self.pick(self.p1, 'Мадара')

	def test_taken_and_foreign_territories_are_refused(self):
		self.play_round([self.p1, self.p2, self.p3])
		with self.assertRaises(InvalidStateError) as caught:
			self.pick(self.p1, 'Езера')
		self.assertEqual(caught.exception.code, 'territory_taken')
		other_game, _ = self.make_game()
		foreign = Territory.objects.get(game=other_game, name='Дунавия')
		with self.assertRaises(InvalidInputError) as caught:
			capture_territory(self.game.pk, self.p1.pk, foreign.pk)
		self.assertEqual(caught.exception.code, 'territory_not_in_game')


class PhaseTests(CaptureTestBase):
	def test_pending_rights_block_the_next_round(self):
		self.play_round([self.p1, self.p2, self.p3])
		self.pick(self.p1, 'Дунавия')
		with self.assertRaises(InvalidStateError) as caught:
			rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(caught.exception.code, 'pending_capture_rights')
		self.pick(self.p1, 'Житно поле')
		self.pick(self.p2, 'Пирина')
		next_round = rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(next_round.number, 2)

	def test_incomplete_ranking_keeps_first_rights_and_leaves_territories(self):
		round_obj = self.play_round([self.p1])
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(
			list(round_obj.capture_rights.values_list('player_id', 'allowed')), [(self.p1.pk, 2)]
		)
		self.pick(self.p1, 'Дунавия')
		self.pick(self.p1, 'Житно поле')
		free_before = Territory.objects.filter(game=self.game, owner__isnull=True).count()
		self.assertEqual(free_before, 13)
		self.assertEqual(rounds.create_city_capture_round(self.game.pk).free_territories_at_creation, 13)

	def test_round_without_winner_gives_no_rights_or_points(self):
		round_obj = rounds.create_city_capture_round(self.game.pk)
		rounds.start_round(round_obj.pk)
		for _ in range(3):
			self.clock.advance(10)
			rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertIsNone(round_obj.winner)
		self.assertFalse(round_obj.capture_rights.exists())
		self.assertFalse(ScoreEvent.objects.filter(game=self.game).exists())
		self.assertEqual(rounds.create_city_capture_round(self.game.pk).number, 2)

	def test_repeated_completion_adds_no_reward_or_rights(self):
		round_obj = self.play_round([self.p1, self.p2, self.p3])
		with self.assertRaises(InvalidStateError):
			rounds.advance_round(round_obj.pk)
		self.assertEqual(round_obj.capture_rights.count(), 2)
		self.assertEqual(self.score(self.p1), WIN_REWARD)


class AtomicityTests(CaptureTestBase):
	def test_failure_mid_capture_rolls_everything_back(self):
		self.play_round([self.p1, self.p2, self.p3])
		with mock.patch('games.scoring._add_to_player', side_effect=RuntimeError('boom')):
			with self.assertRaises(RuntimeError):
				self.pick(self.p1, 'Дунавия')
		territory = self.territory(self.game, 'Дунавия')
		self.assertIsNone(territory.owner)
		self.assertEqual(territory.score, 0)
		self.assertEqual(CaptureRight.objects.get(player=self.p1).used, 0)
		self.assertEqual(self.score(self.p1), WIN_REWARD)
		self.assertFalse(ScoreEvent.objects.filter(kind='capture').exists())
		# A later attempt still works.
		self.pick(self.p1, 'Дунавия')

	def test_stale_last_right_is_used_only_once(self):
		"""Simulates two requests that both read the last unused right."""
		self.leave_free(['Дунавия', 'Житно поле'])
		self.play_round([self.p1])
		self.pick(self.p1, 'Дунавия')
		right = CaptureRight.objects.get(player=self.p1)
		stale = CaptureRight.objects.filter(pk=right.pk)
		self.assertEqual(stale.filter(used=0).update(used=1), 0)  # stale compare-and-set loses
		self.pick(self.p1, 'Житно поле')
		with self.assertRaises(InvalidStateError):
			self.pick(self.p1, 'Житно поле')
		self.assertEqual(ScoreEvent.objects.filter(kind='capture').count(), 2)
