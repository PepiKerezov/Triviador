from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from games.models import CHOICE, NUMERIC, Game, GamePlayer, Round, RoundAnswer
from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


class GameModelTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.user = get_user_model().objects.create_user(
			username='creator',
			email='creator@example.com',
			password='password',
		)
		cls.other_user = get_user_model().objects.create_user(
			username='player',
			email='player@example.com',
			password='password',
		)
		cls.category = Category.objects.create(name='Science')
		cls.choice_question = ChoiceQuestion.objects.create(
			category=cls.category,
			text='What is the chemical symbol for gold?',
		)
		cls.choice_option = AnswerOption.objects.create(
			question=cls.choice_question,
			text='Au',
			is_correct=True,
		)
		cls.numeric_question = NumericQuestion.objects.create(
			category=cls.category,
			text='What is two plus two?',
			correct_answer=4,
		)

	def test_game_relationships_and_defaults(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		player = GamePlayer.objects.create(game=game, user=self.other_user, player_order=1)

		self.assertEqual(game.created_by, self.user)
		self.assertEqual(list(game.players.all()), [player])
		self.assertEqual(player.score, 0)
		self.assertTrue(player.is_active)

	def test_round_and_answer_relationships(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		player = GamePlayer.objects.create(game=game, user=self.other_user, player_order=1)
		round = Round.objects.create(
			game=game,
			number=1,
			status='pending',
			question_type=CHOICE,
			choice_question=self.choice_question,
		)
		answer = RoundAnswer.objects.create(
			round=round,
			player=player,
			selected_option=self.choice_option,
		)

		self.assertEqual(list(game.rounds.all()), [round])
		self.assertEqual(list(round.answers.all()), [answer])
		self.assertEqual(list(player.round_answers.all()), [answer])

	def test_round_requires_question_matching_question_type(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		round = Round(
			game=game,
			number=1,
			status='pending',
			question_type=NUMERIC,
			choice_question=self.choice_question,
		)

		with self.assertRaises(ValidationError):
			round.full_clean()

	def test_answer_requires_value_matching_round_question_type(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		player = GamePlayer.objects.create(game=game, user=self.other_user, player_order=1)
		round = Round.objects.create(
			game=game,
			number=1,
			status='pending',
			question_type=NUMERIC,
			numeric_question=self.numeric_question,
		)
		answer = RoundAnswer(round=round, player=player, selected_option=self.choice_option)

		with self.assertRaises(ValidationError):
			answer.full_clean()