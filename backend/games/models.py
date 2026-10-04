from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion


WAITING = 'waiting'
IN_PROGRESS = 'in_progress'
FINISHED = 'finished'
CANCELLED = 'cancelled'

STATUS_CHOICES = [
	(WAITING, 'Waiting'),
	(IN_PROGRESS, 'In Progress'),
	(FINISHED, 'Finished'),
	(CANCELLED, 'Cancelled'),
]

PENDING = 'pending'
OPEN = 'open'
CLOSED = 'closed'
EVALUATED = 'evaluated'

ROUND_STATUS_CHOICES = [
	(PENDING, 'Pending'),
	(OPEN, 'Open'),
	(CLOSED, 'Closed'),
	(EVALUATED, 'Evaluated'),
]

CHOICE = 'choice'
NUMERIC = 'numeric'

QUESTION_TYPE_CHOICES = [
	(CHOICE, 'Choice'),
	(NUMERIC, 'Numeric'),
]


class Game(models.Model):
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_games',
	)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES)
	created_at = models.DateTimeField(auto_now_add=True)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('created_at',)

	def __str__(self):
		return f'Game {self.pk}'


class GamePlayer(models.Model):
	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='players')
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='game_players',
	)
	player_order = models.PositiveSmallIntegerField()
	score = models.IntegerField(default=0)
	is_active = models.BooleanField(default=True)
	joined_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('player_order',)
		constraints = [
			models.UniqueConstraint(
				fields=('game', 'user'),
				name='unique_game_player_user',
			),
			models.UniqueConstraint(
				fields=('game', 'player_order'),
				name='unique_game_player_order',
			),
		]


class Round(models.Model):
	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='rounds')
	number = models.PositiveIntegerField()
	status = models.CharField(max_length=20, choices=ROUND_STATUS_CHOICES)
	question_type = models.CharField(max_length=10, choices=QUESTION_TYPE_CHOICES)
	choice_question = models.ForeignKey(
		ChoiceQuestion,
		null=True,
		blank=True,
		on_delete=models.PROTECT,
		related_name='game_rounds',
	)
	numeric_question = models.ForeignKey(
		NumericQuestion,
		null=True,
		blank=True,
		on_delete=models.PROTECT,
		related_name='game_rounds',
	)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('number',)
		constraints = [
			models.UniqueConstraint(
				fields=('game', 'number'),
				name='unique_game_round_number',
			),
			models.CheckConstraint(
				condition=(
					models.Q(choice_question__isnull=False, numeric_question__isnull=True)
					| models.Q(choice_question__isnull=True, numeric_question__isnull=False)
				),
				name='round_has_one_question',
			),
		]

	def clean(self):
		super().clean()
		if self.question_type == CHOICE and (self.choice_question_id is None or self.numeric_question_id is not None):
			raise ValidationError('A choice round must use exactly one choice question.')
		if self.question_type == NUMERIC and (self.numeric_question_id is None or self.choice_question_id is not None):
			raise ValidationError('A numeric round must use exactly one numeric question.')


class RoundAnswer(models.Model):
	round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='answers')
	player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='round_answers')
	selected_option = models.ForeignKey(
		AnswerOption,
		null=True,
		blank=True,
		on_delete=models.PROTECT,
		related_name='round_answers',
	)
	numeric_value = models.IntegerField(null=True, blank=True)
	is_correct = models.BooleanField(null=True, blank=True)
	points_awarded = models.IntegerField(default=0)
	submitted_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=('round', 'player'),
				name='unique_round_answer_player',
			),
			models.CheckConstraint(
				condition=(
					models.Q(selected_option__isnull=False, numeric_value__isnull=True)
					| models.Q(selected_option__isnull=True, numeric_value__isnull=False)
				),
				name='answer_has_one_value',
			),
		]

	def clean(self):
		super().clean()
		if self.round_id is None:
			return
		if self.round.question_type == CHOICE and (
			self.selected_option_id is None or self.numeric_value is not None
		):
			raise ValidationError('A choice answer must use exactly one selected option.')
		if self.round.question_type == NUMERIC and (
			self.numeric_value is None or self.selected_option_id is not None
		):
			raise ValidationError('A numeric answer must use exactly one numeric value.')