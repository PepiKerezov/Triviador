"""M06/M08: round lifecycle shared by city_capture, battle and capital_attack.

Public operations (all atomic; refusals raise ``games.errors`` subclasses):

* ``create_city_capture_round(game_id)``
* ``create_battle_round(game_id, attacker_id, territory_id, defender_id=None)``
* ``start_round(round_id)``
* ``submit_answer(round_id, player_id, value)`` - int for numeric, option id for choice
* ``advance_round(round_id)`` - evaluates the current question after all
  answers or after the deadline, then creates the follow-up or completes
* ``get_round_state(round_id)`` - read-only snapshot for reloading a client
"""

import random
from datetime import timedelta
from itertools import groupby

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q

from . import clock, scoring
from .capture import grant_capture_rights, has_pending_capture_rights
from .errors import InvalidInputError, InvalidStateError, RecordNotFoundError
from .models import (
	BATTLE,
	CAPITAL_ATTACK,
	CHOICE,
	CITY_CAPTURE,
	MAX_QUESTIONS_PER_ROUND,
	NUMERIC,
	QUESTION_ACTIVE,
	QUESTION_COMPLETED,
	REASON_BANK_EXHAUSTED,
	REASON_INSUFFICIENT_ANSWERS,
	REASON_LIMIT_REACHED,
	REASON_NONE,
	ROUND_ACTIVE,
	ROUND_COMPLETED,
	ROUND_PENDING,
	Capital,
	Round,
	RoundAnswer,
	RoundParticipant,
	RoundQuestion,
	Territory,
)
from .operations import (
	atomic_operation,
	get_player,
	get_territory,
	lock_active_game,
	parse_integer_answer,
	require_id,
)
from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion

ANSWER_WINDOW = timedelta(seconds=10)
_random = random.SystemRandom()


# --- question selection ------------------------------------------------------

def pick_numeric_question(game):
	used = RoundQuestion.objects.filter(game=game, numeric_question__isnull=False).values(
		'numeric_question_id'
	)
	candidates = [
		pk
		for pk, text in NumericQuestion.objects.exclude(pk__in=used).values_list('pk', 'text')
		if text and text.strip()
	]
	return NumericQuestion.objects.get(pk=_random.choice(candidates)) if candidates else None


def pick_choice_question(game):
	used = RoundQuestion.objects.filter(game=game, choice_question__isnull=False).values(
		'choice_question_id'
	)
	candidates = list(
		ChoiceQuestion.objects.exclude(pk__in=used)
		.annotate(
			option_count=Count('answer_options'),
			correct_count=Count('answer_options', filter=Q(answer_options__is_correct=True)),
		)
		.filter(option_count=4, correct_count=1)
		.exclude(text__regex=r'^\s*$')
		.values_list('pk', flat=True)
	)
	return ChoiceQuestion.objects.get(pk=_random.choice(candidates)) if candidates else None


def _pick(game, question_type):
	return pick_numeric_question(game) if question_type == NUMERIC else pick_choice_question(game)


def _create_question(round_obj, sequence, question_type, bank_question, players, first_place, last_place, start_at=None):
	fields = {
		'round': round_obj,
		'game_id': round_obj.game_id,
		'sequence': sequence,
		'question_type': question_type,
		'text': bank_question.text,
		'first_place': first_place,
		'last_place': last_place,
	}
	if question_type == NUMERIC:
		fields.update(numeric_question=bank_question, correct_answer=bank_question.correct_answer)
	else:
		fields.update(
			choice_question=bank_question,
			options=[
				{'id': option.pk, 'text': option.text, 'is_correct': option.is_correct}
				for option in bank_question.answer_options.order_by('pk')
			],
		)
	if start_at is not None:
		fields.update(status=QUESTION_ACTIVE, started_at=start_at, deadline=start_at + ANSWER_WINDOW)
	question = RoundQuestion.objects.create(**fields)
	question.participants.set(players)
	return question


# --- creation ----------------------------------------------------------------

def _ensure_no_open_work(game):
	if Round.objects.filter(game=game, status__in=(ROUND_PENDING, ROUND_ACTIVE)).exists():
		raise InvalidStateError('The game already has an unfinished round.', 'unfinished_round')
	if has_pending_capture_rights(game):
		raise InvalidStateError('Capture rights must be used first.', 'pending_capture_rights')


def _next_number(game):
	return (game.rounds.aggregate(top=Max('number'))['top'] or 0) + 1


@atomic_operation
def create_city_capture_round(game_id):
	game = lock_active_game(game_id)
	_ensure_no_open_work(game)
	free = Territory.objects.filter(game=game, owner__isnull=True).count()
	if free == 0:
		raise InvalidStateError('All territories are taken; the conquest phase is over.', 'map_full')
	players = list(game.players.filter(is_active=True).order_by('player_order'))
	if len(players) != 3:
		raise InvalidStateError('The game must have three active players.', 'invalid_players')
	question = pick_numeric_question(game)
	if question is None:
		raise InvalidStateError('No unused numeric question is available.', 'question_bank_exhausted')

	required = 2 if free >= 3 else 1
	round_obj = Round.objects.create(
		game=game,
		number=_next_number(game),
		kind=CITY_CAPTURE,
		required_places=required,
		free_territories_at_creation=free,
	)
	RoundParticipant.objects.bulk_create(
		RoundParticipant(round=round_obj, player=player) for player in players
	)
	_create_question(round_obj, 1, NUMERIC, question, players, 1, required)
	return round_obj


@atomic_operation
def create_battle_round(game_id, attacker_id, territory_id, defender_id=None):
	game = lock_active_game(game_id)
	attacker = get_player(game, attacker_id)
	target = get_territory(game, territory_id)
	if target.owner_id is None:
		raise InvalidInputError('A free territory cannot be attacked.', 'territory_free')
	if target.owner_id == attacker.pk:
		raise InvalidInputError('A player cannot attack their own territory.', 'own_territory')
	if defender_id is not None and require_id(defender_id, 'defender_id') != target.owner_id:
		raise InvalidInputError('The defender must be the owner of the target.', 'defender_mismatch')
	if not target.neighbors.filter(owner=attacker).exists():
		raise InvalidInputError(
			'The target is not adjacent to any territory of the attacker.', 'territory_not_adjacent'
		)
	_ensure_no_open_work(game)
	if Territory.objects.filter(game=game, owner__isnull=True).exists():
		raise InvalidStateError('Battles start after every territory is taken.', 'conquest_not_finished')
	question = pick_choice_question(game)
	if question is None:
		raise InvalidStateError('No unused choice question is available.', 'question_bank_exhausted')

	defender = target.owner
	kind = CAPITAL_ATTACK if Capital.objects.filter(territory=target).exists() else BATTLE
	round_obj = Round.objects.create(
		game=game,
		number=_next_number(game),
		kind=kind,
		required_places=1,
		attacker=attacker,
		defender=defender,
		target_territory=target,
	)
	RoundParticipant.objects.bulk_create(
		[RoundParticipant(round=round_obj, player=attacker), RoundParticipant(round=round_obj, player=defender)]
	)
	_create_question(round_obj, 1, CHOICE, question, [attacker, defender], 1, 1)
	return round_obj


# --- lifecycle ---------------------------------------------------------------

def _lock_round(round_id):
	require_id(round_id, 'round_id')
	game_id = Round.objects.filter(pk=round_id).values_list('game_id', flat=True).first()
	if game_id is None:
		raise RecordNotFoundError('The round does not exist.', 'round_not_found')
	game = lock_active_game(game_id)
	return game, Round.objects.select_for_update().get(pk=round_id)


def _active_question(round_obj):
	return round_obj.questions.select_for_update().get(status=QUESTION_ACTIVE)


@atomic_operation
def start_round(round_id):
	_, round_obj = _lock_round(round_id)
	if round_obj.status != ROUND_PENDING:
		raise InvalidStateError('Only a pending round can be started.', 'round_not_pending')
	now = clock.now()
	question = round_obj.questions.get(sequence=1)
	question.status = QUESTION_ACTIVE
	question.started_at = now
	question.deadline = now + ANSWER_WINDOW
	question.save(update_fields=('status', 'started_at', 'deadline'))
	round_obj.status = ROUND_ACTIVE
	round_obj.started_at = now
	round_obj.save(update_fields=('status', 'started_at'))
	return round_obj


@atomic_operation
def submit_answer(round_id, player_id, value):
	# The trusted moment is taken first and used both for the deadline check
	# and as the speed of the answer.
	now = clock.now()
	game, round_obj = _lock_round(round_id)
	player = get_player(game, player_id)
	if round_obj.status != ROUND_ACTIVE:
		raise InvalidStateError('The round is not active.', 'round_not_active')
	question = _active_question(round_obj)
	if not question.participants.filter(pk=player.pk).exists():
		raise InvalidInputError('The player does not take part in this question.', 'not_a_participant')
	if now >= question.deadline:
		raise InvalidStateError('The answer deadline has passed.', 'deadline_passed')
	if question.answers.filter(player=player).exists():
		raise InvalidStateError('The player has already answered.', 'already_answered')

	fields = {'question': question, 'player': player, 'submitted_at': now}
	if question.question_type == NUMERIC:
		number = parse_integer_answer(value)
		fields.update(numeric_value=number, deviation=abs(number - question.correct_answer))
	else:
		option_id = require_id(value, 'option_id')
		option = AnswerOption.objects.filter(pk=option_id).first()
		if option is None:
			raise RecordNotFoundError('The answer option does not exist.', 'option_not_found')
		if option.question_id != question.choice_question_id:
			raise InvalidInputError('The option belongs to another question.', 'option_not_in_question')
		fields.update(selected_option=option, is_correct=option.pk == question.correct_option_id())
	try:
		with transaction.atomic():
			return RoundAnswer.objects.create(**fields)
	except IntegrityError as exc:
		raise InvalidStateError('The player has already answered.', 'already_answered') from exc


def _assign_place(round_obj, player_id, place, question):
	RoundParticipant.objects.filter(round=round_obj, player_id=player_id).update(
		place=place, decided_by=question
	)


def _evaluate_numeric(round_obj, question):
	"""Assign places by closeness, then speed. Return the needed follow-up or None."""
	answers = sorted(question.answers.all(), key=lambda answer: (answer.deviation, answer.submitted_at))
	if not answers:
		return NUMERIC, list(question.participants.all()), question.first_place, question.last_place
	place = question.first_place
	for _, group in groupby(answers, key=lambda answer: (answer.deviation, answer.submitted_at)):
		if place > question.last_place:
			break
		group = list(group)
		if len(group) > 1:
			last = min(question.last_place, place + len(group) - 1)
			return NUMERIC, [answer.player for answer in group], place, last
		_assign_place(round_obj, group[0].player_id, place, question)
		place += 1
	return None


def _evaluate_choice(round_obj, question):
	correct = [answer for answer in question.answers.all() if answer.is_correct]
	if len(correct) == 1:
		_assign_place(round_obj, correct[0].player_id, question.first_place, question)
		return None
	if correct:
		return NUMERIC, [answer.player for answer in correct], question.first_place, question.last_place
	return CHOICE, list(question.participants.all()), question.first_place, question.last_place


def _apply_battle(round_obj, winner):
	target = Territory.objects.select_for_update().get(pk=round_obj.target_territory_id)
	still_valid = target.owner_id == round_obj.defender_id
	if round_obj.kind == CAPITAL_ATTACK:
		still_valid = still_valid and Capital.objects.filter(
			territory=target, player_id=round_obj.defender_id
		).exists()
	if not still_valid:
		raise InvalidStateError('The target no longer matches this battle.', 'target_changed')
	scoring.award_round_win(round_obj, winner)
	if round_obj.kind == BATTLE and winner.pk == round_obj.attacker_id:
		if scoring.capture(round_obj, winner, target.pk, require_owner_id=round_obj.defender_id) is None:
			raise InvalidStateError('The target no longer matches this battle.', 'target_changed')


def _finish(round_obj, now, reason):
	places = {
		participant.place: participant.player
		for participant in round_obj.participants.select_related('player').filter(place__isnull=False)
	}
	if reason == REASON_NONE and any(
		place not in places for place in range(1, round_obj.required_places + 1)
	):
		reason = REASON_INSUFFICIENT_ANSWERS
	winner = places.get(1)
	if winner is not None:
		if round_obj.kind == CITY_CAPTURE:
			scoring.award_round_win(round_obj, winner)
			grant_capture_rights(round_obj, winner, places.get(2))
		else:
			_apply_battle(round_obj, winner)
	round_obj.status = ROUND_COMPLETED
	round_obj.winner = winner
	round_obj.completed_at = now
	round_obj.outcome_reason = reason
	round_obj.full_clean()
	round_obj.save(update_fields=('status', 'winner', 'completed_at', 'outcome_reason'))


@atomic_operation
def advance_round(round_id):
	"""Evaluate the active question; create the follow-up or complete the round."""
	now = clock.now()
	_, round_obj = _lock_round(round_id)
	if round_obj.status == ROUND_COMPLETED:
		raise InvalidStateError('The round is already completed.', 'round_completed')
	if round_obj.status != ROUND_ACTIVE:
		raise InvalidStateError('The round has not started.', 'round_not_active')
	question = _active_question(round_obj)
	group = set(question.participants.values_list('pk', flat=True))
	answered = set(question.answers.values_list('player_id', flat=True))
	if now < question.deadline and answered != group:
		raise InvalidStateError('The question is still open.', 'question_still_open')
	closed = RoundQuestion.objects.filter(pk=question.pk, status=QUESTION_ACTIVE).update(
		status=QUESTION_COMPLETED, completed_at=now
	)
	if closed != 1:
		raise InvalidStateError('The question was closed concurrently.', 'concurrent_access')

	if question.question_type == NUMERIC:
		follow_up = _evaluate_numeric(round_obj, question)
	else:
		follow_up = _evaluate_choice(round_obj, question)
	if follow_up is None:
		_finish(round_obj, now, REASON_NONE)
		return round_obj

	next_type, players, first_place, last_place = follow_up
	if question.sequence >= MAX_QUESTIONS_PER_ROUND:
		_finish(round_obj, now, REASON_LIMIT_REACHED)
		return round_obj
	bank_question = _pick(round_obj.game, next_type)
	if bank_question is None:
		_finish(round_obj, now, REASON_BANK_EXHAUSTED)
		return round_obj
	_create_question(
		round_obj, question.sequence + 1, next_type, bank_question, players, first_place, last_place, start_at=now
	)
	return round_obj


# --- read model --------------------------------------------------------------

def get_round_state(round_id):
	"""Everything a client needs after a reload, computed from stored records."""
	require_id(round_id, 'round_id')
	round_obj = Round.objects.filter(pk=round_id).first()
	if round_obj is None:
		raise RecordNotFoundError('The round does not exist.', 'round_not_found')
	now = clock.now()
	questions = []
	current = None
	for question in round_obj.questions.prefetch_related('participants', 'answers'):
		entry = {
			'sequence': question.sequence,
			'type': question.question_type,
			'bank_question_id': question.bank_question.pk,
			'text': question.text,
			'options': [{'id': o['id'], 'text': o['text']} for o in question.options],
			'participants': sorted(player.pk for player in question.participants.all()),
			'places': [question.first_place, question.last_place],
			'status': question.status,
			'started_at': question.started_at,
			'deadline': question.deadline,
			'answers': [
				{
					'player_id': answer.player_id,
					'numeric_value': answer.numeric_value,
					'option_id': answer.selected_option_id,
					'is_correct': answer.is_correct,
					'deviation': answer.deviation,
					'submitted_at': answer.submitted_at,
				}
				for answer in question.answers.all()
			],
		}
		if question.status == QUESTION_ACTIVE:
			entry['remaining_seconds'] = max(0.0, (question.deadline - now).total_seconds())
			current = entry
		questions.append(entry)
	return {
		'round_id': round_obj.pk,
		'number': round_obj.number,
		'kind': round_obj.kind,
		'status': round_obj.status,
		'required_places': round_obj.required_places,
		'winner_id': round_obj.winner_id,
		'outcome_reason': round_obj.outcome_reason,
		'completed_at': round_obj.completed_at,
		'ranking': {
			participant.place: participant.player_id
			for participant in round_obj.participants.filter(place__isnull=False)
		},
		'current_question': current,
		'questions': questions,
	}
