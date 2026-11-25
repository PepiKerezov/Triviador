from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from django.utils import timezone

from games.models import (
	CHOICE,
	CITY_CAPTURE,
	NUMERIC,
	REASON_LIMIT_REACHED,
	ROUND_COMPLETED,
	Game,
	GamePlayer,
	Round,
	RoundAnswer,
	RoundQuestion,
)
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

	def make_round(self, game):
		return Round.objects.create(game=game, number=1, kind=CITY_CAPTURE, required_places=1)

	def make_question(self, round, question_type):
		fields = {'round': round, 'game': round.game, 'sequence': 1, 'question_type': question_type,
			'text': 'Q', 'first_place': 1, 'last_place': 1}
		if question_type == CHOICE:
			fields['choice_question'] = self.choice_question
		else:
			fields.update(numeric_question=self.numeric_question, correct_answer=4)
		return RoundQuestion.objects.create(**fields)

	def test_round_and_answer_relationships(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		player = GamePlayer.objects.create(game=game, user=self.other_user, player_order=1)
		round = self.make_round(game)
		question = self.make_question(round, CHOICE)
		answer = RoundAnswer.objects.create(
			question=question,
			player=player,
			selected_option=self.choice_option,
			is_correct=True,
			submitted_at=timezone.now(),
		)

		self.assertEqual(list(game.rounds.all()), [round])
		self.assertEqual(game.get_current_round(), round)
		self.assertEqual(list(round.questions.all()), [question])
		self.assertEqual(list(question.answers.all()), [answer])
		self.assertEqual(list(player.round_answers.all()), [answer])

	def test_round_question_requires_question_matching_type(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		question = RoundQuestion(
			round=self.make_round(game),
			game=game,
			sequence=1,
			question_type=NUMERIC,
			choice_question=self.choice_question,
			text='Q',
			first_place=1,
			last_place=1,
		)

		with self.assertRaises(ValidationError):
			question.full_clean()

	def test_answer_requires_value_matching_question_type(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		player = GamePlayer.objects.create(game=game, user=self.other_user, player_order=1)
		question = self.make_question(self.make_round(game), NUMERIC)
		answer = RoundAnswer(
			question=question, player=player, selected_option=self.choice_option, submitted_at=timezone.now()
		)

		with self.assertRaises(ValidationError):
			answer.full_clean()

	def test_completed_round_without_winner_needs_reason(self):
		game = Game.objects.create(created_by=self.user, status='waiting')
		round = self.make_round(game)
		round.status = ROUND_COMPLETED
		round.completed_at = timezone.now()
		with self.assertRaises(ValidationError):
			round.full_clean()
		round.outcome_reason = REASON_LIMIT_REACHED
		round.full_clean()
