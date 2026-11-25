from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion


WAITING = 'waiting'
ACTIVE = 'active'
IN_PROGRESS = 'in_progress'
FINISHED = 'finished'
CANCELLED = 'cancelled'

STATUS_CHOICES = [
	(WAITING, 'Waiting'),
	(ACTIVE, 'Active'),
	(IN_PROGRESS, 'In Progress'),
	(FINISHED, 'Finished'),
	(CANCELLED, 'Cancelled'),
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

	def get_current_round(self):
		"""Return the round with the highest number, or None."""
		return self.rounds.order_by('-number').first()


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
			models.CheckConstraint(
				condition=models.Q(score__gte=0),
				name='game_player_score_non_negative',
			),
		]

	def __str__(self):
		return f'{self.user} (game {self.game_id})'


class Territory(models.Model):
	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='territories')
	name = models.CharField(max_length=100)
	slug = models.SlugField(max_length=100, allow_unicode=True)
	owner = models.ForeignKey(
		GamePlayer,
		null=True,
		blank=True,
		on_delete=models.PROTECT,
		related_name='territories',
	)
	score = models.PositiveIntegerField(default=0)
	neighbors = models.ManyToManyField('self', symmetrical=True, blank=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=('game', 'name'), name='unique_territory_name_per_game'),
			models.UniqueConstraint(fields=('game', 'slug'), name='unique_territory_slug_per_game'),
		]

	def clean(self):
		super().clean()
		self.name = self.name.strip()
		self.slug = self.slug.strip().lower()
		if not self.name:
			raise ValidationError({'name': 'Territory name cannot be blank.'})
		if not self.slug:
			raise ValidationError({'slug': 'Territory slug cannot be blank.'})
		if self.owner_id and self.game_id and self.owner.game_id != self.game_id:
			raise ValidationError({'owner': 'Territory owner must belong to the same game.'})

	def save(self, *args, **kwargs):
		self.full_clean()
		return super().save(*args, **kwargs)

	def set_neighbors(self, neighbors):
		neighbors = list(neighbors)
		if any(neighbor.pk == self.pk for neighbor in neighbors):
			raise ValidationError('A territory cannot be its own neighbor.')
		if any(neighbor.game_id != self.game_id for neighbor in neighbors):
			raise ValidationError('Territory neighbors must belong to the same game.')
		if len({neighbor.pk for neighbor in neighbors}) != len(neighbors):
			raise ValidationError('A territory cannot have duplicate neighbors.')
		if len(neighbors) < 2:
			raise ValidationError('A territory must have at least two neighbors.')
		self.neighbors.set(neighbors)

	def __str__(self):
		return self.name


class Capital(models.Model):
	territory = models.OneToOneField(
		Territory,
		on_delete=models.PROTECT,
		related_name='capital',
	)
	player = models.OneToOneField(
		GamePlayer,
		on_delete=models.PROTECT,
		related_name='capital',
	)
	health = models.PositiveSmallIntegerField(default=3)

	class Meta:
		constraints = [
			models.CheckConstraint(
				condition=models.Q(health__gte=0, health__lte=3),
				name='capital_health_between_zero_and_three',
			),
		]

	def clean(self):
		super().clean()
		if self.territory_id and self.player_id:
			if self.territory.game_id != self.player.game_id:
				raise ValidationError('Capital territory and player must belong to the same game.')
			if self.territory.owner_id != self.player_id:
				raise ValidationError('Capital territory must be owned by its player.')

	def save(self, *args, **kwargs):
		self.full_clean()
		return super().save(*args, **kwargs)


# --- Rounds (M06-M08) -------------------------------------------------------

ROUND_PENDING = 'pending'
ROUND_ACTIVE = 'active'
ROUND_COMPLETED = 'completed'

ROUND_STATUS_CHOICES = [
	(ROUND_PENDING, 'Pending'),
	(ROUND_ACTIVE, 'Active'),
	(ROUND_COMPLETED, 'Completed'),
]

CITY_CAPTURE = 'city_capture'
BATTLE = 'battle'
CAPITAL_ATTACK = 'capital_attack'

ROUND_KIND_CHOICES = [
	(CITY_CAPTURE, 'City capture'),
	(BATTLE, 'Battle'),
	(CAPITAL_ATTACK, 'Capital attack'),
]

# Why a completed round has an incomplete ranking (or no winner).
REASON_NONE = ''
REASON_LIMIT_REACHED = 'limit_reached'
REASON_BANK_EXHAUSTED = 'bank_exhausted'
REASON_INSUFFICIENT_ANSWERS = 'insufficient_answers'

OUTCOME_REASON_CHOICES = [
	(REASON_NONE, 'Complete'),
	(REASON_LIMIT_REACHED, 'Question limit reached'),
	(REASON_BANK_EXHAUSTED, 'Question bank exhausted'),
	(REASON_INSUFFICIENT_ANSWERS, 'Not enough accepted answers'),
]

QUESTION_PENDING = 'pending'
QUESTION_ACTIVE = 'active'
QUESTION_COMPLETED = 'completed'

QUESTION_STATUS_CHOICES = [
	(QUESTION_PENDING, 'Pending'),
	(QUESTION_ACTIVE, 'Active'),
	(QUESTION_COMPLETED, 'Completed'),
]

MAX_QUESTIONS_PER_ROUND = 3


class Round(models.Model):
	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='rounds')
	number = models.PositiveIntegerField()
	kind = models.CharField(max_length=20, choices=ROUND_KIND_CHOICES)
	status = models.CharField(max_length=20, choices=ROUND_STATUS_CHOICES, default=ROUND_PENDING)
	# Number of ranked places this round must determine; fixed at creation.
	required_places = models.PositiveSmallIntegerField()
	# city_capture: free territories counted at creation (drives capture rights).
	free_territories_at_creation = models.PositiveSmallIntegerField(null=True, blank=True)
	# battle / capital_attack
	attacker = models.ForeignKey(
		GamePlayer, null=True, blank=True, on_delete=models.PROTECT, related_name='attacks'
	)
	defender = models.ForeignKey(
		GamePlayer, null=True, blank=True, on_delete=models.PROTECT, related_name='defences'
	)
	target_territory = models.ForeignKey(
		Territory, null=True, blank=True, on_delete=models.PROTECT, related_name='battles'
	)
	winner = models.ForeignKey(
		GamePlayer, null=True, blank=True, on_delete=models.PROTECT, related_name='won_rounds'
	)
	outcome_reason = models.CharField(
		max_length=30, choices=OUTCOME_REASON_CHOICES, default=REASON_NONE, blank=True
	)
	created_at = models.DateTimeField(auto_now_add=True)
	started_at = models.DateTimeField(null=True, blank=True)
	completed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('number',)
		constraints = [
			models.UniqueConstraint(fields=('game', 'number'), name='unique_game_round_number'),
			models.UniqueConstraint(
				fields=('game',),
				condition=models.Q(status__in=(ROUND_PENDING, ROUND_ACTIVE)),
				name='one_unfinished_round_per_game',
			),
			models.CheckConstraint(
				condition=models.Q(required_places__gte=1, required_places__lte=2),
				name='round_required_places_range',
			),
			models.CheckConstraint(
				condition=(
					models.Q(status=ROUND_COMPLETED, completed_at__isnull=False)
					| (~models.Q(status=ROUND_COMPLETED) & models.Q(completed_at__isnull=True))
				),
				name='round_completed_at_matches_status',
			),
			models.CheckConstraint(
				condition=models.Q(winner__isnull=True) | models.Q(status=ROUND_COMPLETED),
				name='round_winner_only_when_completed',
			),
			models.CheckConstraint(
				condition=(
					~models.Q(status=ROUND_COMPLETED)
					| models.Q(winner__isnull=False)
					| ~models.Q(outcome_reason=REASON_NONE)
				),
				name='round_without_winner_has_reason',
			),
			models.CheckConstraint(
				condition=(
					models.Q(
						kind=CITY_CAPTURE,
						attacker__isnull=True,
						defender__isnull=True,
						target_territory__isnull=True,
					)
					| models.Q(
						kind__in=(BATTLE, CAPITAL_ATTACK),
						attacker__isnull=False,
						defender__isnull=False,
						target_territory__isnull=False,
					)
				),
				name='round_battle_fields_match_kind',
			),
		]

	def clean(self):
		super().clean()
		if self.status == ROUND_COMPLETED and self.completed_at is None:
			raise ValidationError('A completed round must have completed_at.')
		if self.status != ROUND_COMPLETED and (self.completed_at or self.winner_id):
			raise ValidationError('Only a completed round has a winner and completed_at.')
		if self.status == ROUND_COMPLETED and not self.winner_id and not self.outcome_reason:
			raise ValidationError('A completed round without a winner needs an outcome reason.')
		if self.kind in (BATTLE, CAPITAL_ATTACK):
			if self.attacker_id is None or self.defender_id is None or self.target_territory_id is None:
				raise ValidationError('A battle needs an attacker, a defender and a target.')
			if self.attacker_id == self.defender_id:
				raise ValidationError('Attacker and defender must be different players.')

	def __str__(self):
		return f'Round {self.number} ({self.kind}) of game {self.game_id}'


class RoundParticipant(models.Model):
	round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='participants')
	player = models.ForeignKey(GamePlayer, on_delete=models.PROTECT, related_name='round_participations')
	place = models.PositiveSmallIntegerField(null=True, blank=True)
	decided_by = models.ForeignKey(
		'RoundQuestion', null=True, blank=True, on_delete=models.PROTECT, related_name='decided_places'
	)

	class Meta:
		ordering = ('round', 'place', 'player__player_order')
		constraints = [
			models.UniqueConstraint(fields=('round', 'player'), name='unique_round_participant'),
			models.UniqueConstraint(fields=('round', 'place'), name='unique_round_place'),
			models.CheckConstraint(
				condition=(
					models.Q(place__isnull=True, decided_by__isnull=True)
					| models.Q(place__gte=1, decided_by__isnull=False)
				),
				name='round_place_has_deciding_question',
			),
		]


class RoundQuestion(models.Model):
	"""One question asked inside a round (the initial one or a follow-up).

	The bank question is referenced through one of two typed foreign keys, so
	``ChoiceQuestion(5)`` and ``NumericQuestion(5)`` never collide. The text and
	correct answer are copied at creation, so later bank edits do not change
	what was asked or how it was scored.
	"""

	round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='questions')
	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='asked_questions')
	sequence = models.PositiveSmallIntegerField()
	question_type = models.CharField(max_length=10, choices=QUESTION_TYPE_CHOICES)
	choice_question = models.ForeignKey(
		ChoiceQuestion, null=True, blank=True, on_delete=models.PROTECT, related_name='game_rounds'
	)
	numeric_question = models.ForeignKey(
		NumericQuestion, null=True, blank=True, on_delete=models.PROTECT, related_name='game_rounds'
	)
	text = models.TextField()
	correct_answer = models.BigIntegerField(null=True, blank=True)
	options = models.JSONField(default=list, blank=True)
	# Places this question decides: first_place..last_place (inclusive).
	first_place = models.PositiveSmallIntegerField()
	last_place = models.PositiveSmallIntegerField()
	participants = models.ManyToManyField(GamePlayer, related_name='asked_round_questions')
	status = models.CharField(max_length=20, choices=QUESTION_STATUS_CHOICES, default=QUESTION_PENDING)
	started_at = models.DateTimeField(null=True, blank=True)
	deadline = models.DateTimeField(null=True, blank=True)
	completed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('round', 'sequence')
		constraints = [
			models.UniqueConstraint(fields=('round', 'sequence'), name='unique_round_question_sequence'),
			models.UniqueConstraint(
				fields=('game', 'choice_question'), name='choice_question_once_per_game'
			),
			models.UniqueConstraint(
				fields=('game', 'numeric_question'), name='numeric_question_once_per_game'
			),
			models.CheckConstraint(
				condition=models.Q(sequence__gte=1, sequence__lte=MAX_QUESTIONS_PER_ROUND),
				name='round_question_sequence_range',
			),
			models.CheckConstraint(
				condition=(
					models.Q(
						question_type=CHOICE,
						choice_question__isnull=False,
						numeric_question__isnull=True,
					)
					| models.Q(
						question_type=NUMERIC,
						choice_question__isnull=True,
						numeric_question__isnull=False,
						correct_answer__isnull=False,
					)
				),
				name='round_question_matches_type',
			),
			models.CheckConstraint(
				condition=models.Q(first_place__gte=1, last_place__gte=models.F('first_place')),
				name='round_question_place_range',
			),
			models.CheckConstraint(
				condition=(
					models.Q(status=QUESTION_PENDING, started_at__isnull=True, deadline__isnull=True)
					| (
						~models.Q(status=QUESTION_PENDING)
						& models.Q(started_at__isnull=False, deadline__isnull=False)
					)
				),
				name='round_question_timing_matches_status',
			),
		]

	def clean(self):
		super().clean()
		if self.question_type == CHOICE and (self.choice_question_id is None or self.numeric_question_id is not None):
			raise ValidationError('A choice step must use exactly one choice question.')
		if self.question_type == NUMERIC and (self.numeric_question_id is None or self.choice_question_id is not None):
			raise ValidationError('A numeric step must use exactly one numeric question.')
		if self.round_id and self.game_id and self.round.game_id != self.game_id:
			raise ValidationError('A round question must belong to the round game.')

	@property
	def bank_question(self):
		return self.choice_question if self.question_type == CHOICE else self.numeric_question

	def correct_option_id(self):
		for option in self.options:
			if option['is_correct']:
				return option['id']
		return None

	def __str__(self):
		return f'Q{self.sequence} of round {self.round_id} ({self.question_type})'


class RoundAnswer(models.Model):
	question = models.ForeignKey(RoundQuestion, on_delete=models.CASCADE, related_name='answers')
	player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='round_answers')
	selected_option = models.ForeignKey(
		AnswerOption,
		null=True,
		blank=True,
		on_delete=models.PROTECT,
		related_name='round_answers',
	)
	numeric_value = models.BigIntegerField(null=True, blank=True)
	# Evaluated against the snapshot on the RoundQuestion when accepted.
	is_correct = models.BooleanField(null=True, blank=True)
	deviation = models.PositiveBigIntegerField(null=True, blank=True)
	submitted_at = models.DateTimeField()

	class Meta:
		ordering = ('question', 'submitted_at')
		constraints = [
			models.UniqueConstraint(
				fields=('question', 'player'),
				name='unique_round_answer_player',
			),
			models.CheckConstraint(
				condition=(
					models.Q(selected_option__isnull=False, numeric_value__isnull=True, is_correct__isnull=False)
					| models.Q(selected_option__isnull=True, numeric_value__isnull=False, deviation__isnull=False)
				),
				name='answer_has_one_value',
			),
		]

	def clean(self):
		super().clean()
		if self.question_id is None:
			return
		if self.question.question_type == CHOICE and (
			self.selected_option_id is None or self.numeric_value is not None
		):
			raise ValidationError('A choice answer must use exactly one selected option.')
		if self.question.question_type == NUMERIC and (
			self.numeric_value is None or self.selected_option_id is not None
		):
			raise ValidationError('A numeric answer must use exactly one numeric value.')
		if (
			self.selected_option_id is not None
			and self.selected_option.question_id != self.question.choice_question_id
		):
			raise ValidationError('The selected option must belong to the asked question.')


# --- Capture rights and scoring (M07-M08) -----------------------------------

class CaptureRight(models.Model):
	"""A right, earned in a city_capture round, to pick free territories."""

	round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='capture_rights')
	player = models.ForeignKey(GamePlayer, on_delete=models.PROTECT, related_name='capture_rights')
	order = models.PositiveSmallIntegerField()
	allowed = models.PositiveSmallIntegerField()
	used = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ('round', 'order')
		constraints = [
			models.UniqueConstraint(fields=('round', 'player'), name='unique_capture_right_player'),
			models.UniqueConstraint(fields=('round', 'order'), name='unique_capture_right_order'),
			models.CheckConstraint(
				condition=models.Q(allowed__gte=1, allowed__lte=2, used__lte=models.F('allowed')),
				name='capture_right_usage_range',
			),
		]

	@property
	def remaining(self):
		return self.allowed - self.used


SCORE_ROUND_WIN = 'round_win'
SCORE_CAPTURE = 'capture'

SCORE_KIND_CHOICES = [
	(SCORE_ROUND_WIN, 'Round win'),
	(SCORE_CAPTURE, 'Territory capture'),
]


class ScoreEvent(models.Model):
	"""Audit record of one score change, with values before and after."""

	game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='score_events')
	round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='score_events')
	player = models.ForeignKey(GamePlayer, on_delete=models.PROTECT, related_name='score_events')
	kind = models.CharField(max_length=20, choices=SCORE_KIND_CHOICES)
	territory = models.ForeignKey(
		Territory, null=True, blank=True, on_delete=models.PROTECT, related_name='score_events'
	)
	points = models.PositiveIntegerField()
	player_score_before = models.PositiveIntegerField()
	player_score_after = models.PositiveIntegerField()
	territory_score_before = models.PositiveIntegerField(null=True, blank=True)
	territory_score_after = models.PositiveIntegerField(null=True, blank=True)
	calculation = models.CharField(max_length=255)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('created_at', 'pk')
		constraints = [
			models.UniqueConstraint(
				fields=('round',),
				condition=models.Q(kind=SCORE_ROUND_WIN),
				name='one_win_reward_per_round',
			),
			models.UniqueConstraint(
				fields=('round', 'territory'),
				condition=models.Q(kind=SCORE_CAPTURE),
				name='one_capture_reward_per_territory_and_round',
			),
			models.CheckConstraint(
				condition=models.Q(
					points__gte=1,
					player_score_after=models.F('player_score_before') + models.F('points'),
				),
				name='score_event_adds_points',
			),
			models.CheckConstraint(
				condition=(
					models.Q(kind=SCORE_ROUND_WIN, territory__isnull=True)
					| models.Q(
						kind=SCORE_CAPTURE,
						territory__isnull=False,
						territory_score_before__isnull=False,
						territory_score_after__gt=models.F('territory_score_before'),
					)
				),
				name='score_event_territory_matches_kind',
			),
		]
