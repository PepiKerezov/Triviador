from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from django.utils import timezone

from games.models import CITY_CAPTURE, Game, GamePlayer, Round, RoundAnswer, RoundQuestion
from questions.models import AnswerOption, Category, ChoiceQuestion


class GameConstraintTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = get_user_model().objects.create_user(
			username='creator',
			email='creator@example.com',
			password='password',
		)
		cls.player_user = get_user_model().objects.create_user(
			username='player',
			email='player@example.com',
			password='password',
		)
		cls.category = Category.objects.create(name='Science')
		cls.question = ChoiceQuestion.objects.create(category=cls.category, text='Question')
		cls.option = AnswerOption.objects.create(
			question=cls.question,
			text='Answer',
			is_correct=True,
		)

	def setUp(self):
		self.game = Game.objects.create(created_by=self.user, status='waiting')
		self.player = GamePlayer.objects.create(
			game=self.game,
			user=self.player_user,
			player_order=1,
		)
		self.round = Round.objects.create(
			game=self.game, number=1, kind=CITY_CAPTURE, required_places=1
		)
		self.round_question = RoundQuestion.objects.create(
			round=self.round,
			game=self.game,
			sequence=1,
			question_type='choice',
			choice_question=self.question,
			text='Question',
			first_place=1,
			last_place=1,
		)

	def test_game_player_user_is_unique_per_game(self):
		with self.assertRaises(IntegrityError):
			GamePlayer.objects.create(game=self.game, user=self.player_user, player_order=2)

	def test_round_number_is_unique_per_game(self):
		with self.assertRaises(IntegrityError):
			Round.objects.create(
				game=self.game, number=1, kind=CITY_CAPTURE, required_places=1, status='completed',
				completed_at=timezone.now(), outcome_reason='limit_reached',
			)

	def test_player_can_answer_round_only_once(self):
		RoundAnswer.objects.create(
			question=self.round_question,
			player=self.player,
			selected_option=self.option,
			is_correct=True,
			submitted_at=timezone.now(),
		)

		with self.assertRaises(IntegrityError):
			RoundAnswer.objects.create(
				question=self.round_question,
				player=self.player,
				selected_option=self.option,
				is_correct=True,
				submitted_at=timezone.now(),
			)
	def test_only_one_unfinished_round_per_game(self):
		with self.assertRaises(IntegrityError):
			Round.objects.create(game=self.game, number=2, kind=CITY_CAPTURE, required_places=1)

	def test_bank_question_is_used_once_per_game(self):
		round = Round.objects.create(
			game=self.game, number=2, kind=CITY_CAPTURE, required_places=1, status='completed',
			completed_at=timezone.now(), outcome_reason='limit_reached',
		)
		with self.assertRaises(IntegrityError):
			RoundQuestion.objects.create(
				round=round, game=self.game, sequence=1, question_type='choice',
				choice_question=self.question, text='Question', first_place=1, last_place=1,
			)
