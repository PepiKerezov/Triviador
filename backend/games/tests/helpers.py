from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model

from games.models import Game, GamePlayer, Territory
from games.services import initialize_game
from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion

# Deterministic capitals: player_order 1, 2, 3 (pairwise non-adjacent).
CAPITALS = ('Скали', 'Езера', 'Слънчево')


class FakeClock:
	def __init__(self):
		self.current = datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc)

	def __call__(self):
		return self.current

	def advance(self, seconds):
		self.current += timedelta(seconds=seconds)


class _FixedRandom:
	def choice(self, sequence):
		return CAPITALS

	def shuffle(self, sequence):
		pass


class GameTestMixin:
	"""Users, an active game with fixed capitals, a fake clock and a bank."""

	@classmethod
	def make_users(cls, prefix):
		model = get_user_model()
		cls.creator = model.objects.create_user(
			username=f'{prefix}_creator', email=f'{prefix}_creator@example.com', password='password'
		)
		cls.users = [
			model.objects.create_user(
				username=f'{prefix}_{index}', email=f'{prefix}_{index}@example.com', password='password'
			)
			for index in range(3)
		]

	@classmethod
	def make_bank(cls, numeric=6, choice=0, name='Bank'):
		category = Category.objects.create(name=name)
		numerics = [
			NumericQuestion.objects.create(
				category=category, text=f'Numeric {index}', correct_answer=100 * (index + 1)
			)
			for index in range(numeric)
		]
		choices = []
		for index in range(choice):
			question = ChoiceQuestion.objects.create(category=category, text=f'Choice {index}')
			for option_index in range(4):
				AnswerOption.objects.create(
					question=question, text=f'Option {option_index}', is_correct=option_index == 0
				)
			choices.append(question)
		return numerics, choices

	def setUp(self):
		super().setUp()
		self.clock = FakeClock()
		patcher = mock.patch('games.clock.now', self.clock)
		patcher.start()
		self.addCleanup(patcher.stop)

	def make_game(self, initialize=True):
		game = Game.objects.create(created_by=self.creator, status='waiting')
		players = [
			GamePlayer.objects.create(game=game, user=user, player_order=index)
			for index, user in enumerate(self.users, start=1)
		]
		if initialize:
			with mock.patch('games.services.random.SystemRandom', return_value=_FixedRandom()):
				initialize_game(game.pk)
			game.refresh_from_db()
		return game, players

	@staticmethod
	def territory(game, name):
		return Territory.objects.get(game=game, name=name)

	@staticmethod
	def set_owner(game, names, player, score=None):
		queryset = Territory.objects.filter(game=game, name__in=names)
		assert queryset.count() == len(names)
		update = {'owner': player}
		if score is not None:
			update['score'] = score
		queryset.update(**update)

	@staticmethod
	def correct_option(question):
		return question.choice_question.answer_options.get(is_correct=True)

	@staticmethod
	def wrong_option(question):
		return question.choice_question.answer_options.filter(is_correct=False).first()
