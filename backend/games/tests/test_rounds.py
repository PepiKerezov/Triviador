from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase

from games import rounds
from games.errors import InvalidInputError, InvalidStateError, RecordNotFoundError
from games.models import (
	QUESTION_ACTIVE,
	QUESTION_COMPLETED,
	QUESTION_PENDING,
	REASON_BANK_EXHAUSTED,
	REASON_INSUFFICIENT_ANSWERS,
	REASON_LIMIT_REACHED,
	REASON_NONE,
	ROUND_ACTIVE,
	ROUND_COMPLETED,
	ROUND_PENDING,
	Round,
	RoundAnswer,
	ScoreEvent,
)
from questions.models import NumericQuestion

from .helpers import GameTestMixin


class RoundTestBase(GameTestMixin, TestCase):
	numeric_count = 6

	@classmethod
	def setUpTestData(cls):
		cls.make_users('rounds')
		cls.numerics, _ = cls.make_bank(numeric=cls.numeric_count)

	def setUp(self):
		super().setUp()
		self.game, self.players = self.make_game()
		self.p1, self.p2, self.p3 = self.players

	def started_round(self):
		round_obj = rounds.create_city_capture_round(self.game.pk)
		rounds.start_round(round_obj.pk)
		return round_obj

	def current(self, round_obj):
		return round_obj.questions.get(status=QUESTION_ACTIVE)

	def answer(self, round_obj, player, offset, after=0.0):
		"""Answer the current question with correct_answer + offset."""
		self.clock.advance(after)
		question = self.current(round_obj)
		return rounds.submit_answer(round_obj.pk, player.pk, question.correct_answer + offset)

	def finish_question(self, round_obj):
		self.clock.advance(10)
		return rounds.advance_round(round_obj.pk)

	def ranking(self, round_obj):
		return rounds.get_round_state(round_obj.pk)['ranking']


class RoundWorkflowTests(RoundTestBase):
	def test_create_start_and_complete(self):
		round_obj = rounds.create_city_capture_round(self.game.pk)
		question = round_obj.questions.get()
		self.assertEqual(round_obj.number, 1)
		self.assertEqual(round_obj.status, ROUND_PENDING)
		self.assertEqual(round_obj.required_places, 2)
		self.assertEqual(question.status, QUESTION_PENDING)
		self.assertIsNone(question.deadline)
		self.assertEqual(set(question.participants.all()), set(self.players))
		self.assertEqual(self.game.get_current_round(), round_obj)

		start = self.clock()
		rounds.start_round(round_obj.pk)
		question.refresh_from_db()
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.status, ROUND_ACTIVE)
		self.assertEqual(question.started_at, start)
		self.assertEqual(question.deadline, start + timedelta(seconds=10))

		self.answer(round_obj, self.p1, 0, after=1)
		self.answer(round_obj, self.p2, 5, after=1)
		self.answer(round_obj, self.p3, -10, after=1)
		rounds.advance_round(round_obj.pk)  # all answered: no need to wait

		round_obj.refresh_from_db()
		self.assertEqual(round_obj.status, ROUND_COMPLETED)
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(round_obj.completed_at, self.clock())
		self.assertEqual(round_obj.outcome_reason, REASON_NONE)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk, 2: self.p2.pk})

	def test_closeness_beats_speed(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 50, after=0.1)
		self.answer(round_obj, self.p2, 1, after=5)
		self.finish_question(round_obj)
		self.assertEqual(self.ranking(round_obj), {1: self.p2.pk, 2: self.p1.pk})

	def test_equal_closeness_on_both_sides_is_decided_by_speed(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 7, after=0.5)
		self.answer(round_obj, self.p2, -7, after=0.000001)
		self.answer(round_obj, self.p3, 30, after=0.5)
		rounds.advance_round(round_obj.pk)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk, 2: self.p2.pk})

	def test_single_answer_gives_only_first_place(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p3, 1000)
		self.finish_question(round_obj)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p3)
		self.assertEqual(self.ranking(round_obj), {1: self.p3.pk})
		self.assertEqual(round_obj.outcome_reason, REASON_INSUFFICIENT_ANSWERS)
		self.assertEqual(round_obj.questions.count(), 1)

	def test_next_round_number_follows_the_highest(self):
		Round.objects.create(
			game=self.game, number=7, kind='city_capture', required_places=1, status=ROUND_COMPLETED,
			completed_at=self.clock(), outcome_reason=REASON_LIMIT_REACHED,
		)
		round_obj = rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(round_obj.number, 8)


class RoundRefusalTests(RoundTestBase):
	def test_foreign_player_is_invalid_input(self):
		other_game, other_players = self.make_game(initialize=False)
		round_obj = self.started_round()
		with self.assertRaises(InvalidInputError) as caught:
			rounds.submit_answer(round_obj.pk, other_players[0].pk, 5)
		self.assertEqual(caught.exception.code, 'player_not_in_game')

	def test_missing_records_are_not_found(self):
		with self.assertRaises(RecordNotFoundError) as caught:
			rounds.start_round(999999)
		self.assertEqual(caught.exception.code, 'round_not_found')
		with self.assertRaises(RecordNotFoundError):
			rounds.create_city_capture_round(999999)

	def test_repeated_answer_keeps_the_first(self):
		round_obj = self.started_round()
		first = self.answer(round_obj, self.p1, 3)
		with self.assertRaises(InvalidStateError) as caught:
			self.answer(round_obj, self.p1, 0)
		self.assertEqual(caught.exception.code, 'already_answered')
		self.assertEqual(list(RoundAnswer.objects.filter(player=self.p1)), [first])
		self.assertEqual(RoundAnswer.objects.get(player=self.p1).deviation, 3)

	def test_invalid_value_does_not_use_the_answer_right(self):
		round_obj = self.started_round()
		for bad in (3.5, '3.5', 4.0, True, None, 'abc', 10**16):
			with self.assertRaises(InvalidInputError) as caught:
				rounds.submit_answer(round_obj.pk, self.p1.pk, bad)
			self.assertEqual(caught.exception.code, 'invalid_value')
		answer = rounds.submit_answer(round_obj.pk, self.p1.pk, ' 42 ')
		self.assertEqual(answer.numeric_value, 42)

	def test_answer_before_start_is_refused(self):
		round_obj = rounds.create_city_capture_round(self.game.pk)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.submit_answer(round_obj.pk, self.p1.pk, 1)
		self.assertEqual(caught.exception.code, 'round_not_active')

	def test_repeated_completion_and_start_are_refused(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 0)
		self.finish_question(round_obj)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.advance_round(round_obj.pk)
		self.assertEqual(caught.exception.code, 'round_completed')
		with self.assertRaises(InvalidStateError):
			rounds.start_round(round_obj.pk)
		self.assertEqual(ScoreEvent.objects.filter(round=round_obj, kind='round_win').count(), 1)

	def test_premature_completion_is_refused(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 0, after=9)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.advance_round(round_obj.pk)
		self.assertEqual(caught.exception.code, 'question_still_open')
		self.assertEqual(self.current(round_obj).status, QUESTION_ACTIVE)

	def test_inactive_game_blocks_every_operation(self):
		round_obj = self.started_round()
		self.game.status = 'finished'
		self.game.save()
		for call in (
			lambda: rounds.create_city_capture_round(self.game.pk),
			lambda: rounds.submit_answer(round_obj.pk, self.p1.pk, 1),
			lambda: rounds.advance_round(round_obj.pk),
		):
			with self.assertRaises(InvalidStateError) as caught:
				call()
			self.assertEqual(caught.exception.code, 'game_not_active')

	def test_second_unfinished_round_is_refused(self):
		rounds.create_city_capture_round(self.game.pk)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(caught.exception.code, 'unfinished_round')
		self.assertEqual(self.game.rounds.count(), 1)


class DeadlineTests(RoundTestBase):
	def test_just_before_deadline_is_accepted(self):
		round_obj = self.started_round()
		answer = self.answer(round_obj, self.p1, 0, after=9.999999)
		self.assertEqual(answer.submitted_at, self.current(round_obj).deadline - timedelta(microseconds=1))

	def test_exactly_at_deadline_is_refused(self):
		round_obj = self.started_round()
		self.clock.advance(10)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.submit_answer(round_obj.pk, self.p1.pk, 1)
		self.assertEqual(caught.exception.code, 'deadline_passed')

	def test_after_deadline_is_refused_and_completion_allowed(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p2, 0)
		self.clock.advance(11)
		with self.assertRaises(InvalidStateError):
			rounds.submit_answer(round_obj.pk, self.p1.pk, 1)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p2)


class FollowUpTests(RoundTestBase):
	def test_full_tie_for_first_asks_only_the_tied_group(self):
		round_obj = self.started_round()
		self.clock.advance(2)
		self.answer(round_obj, self.p1, 4)
		self.answer(round_obj, self.p2, -4)  # same closeness, same trusted moment
		self.answer(round_obj, self.p3, 90, after=1)
		first = self.current(round_obj)
		self.clock.advance(3)
		rounds.advance_round(round_obj.pk)

		follow_up = self.current(round_obj)
		self.assertEqual(follow_up.sequence, 2)
		self.assertNotEqual(follow_up.numeric_question_id, first.numeric_question_id)
		self.assertEqual(set(follow_up.participants.all()), {self.p1, self.p2})
		self.assertEqual((follow_up.first_place, follow_up.last_place), (1, 2))
		self.assertEqual(follow_up.started_at, self.clock())
		self.assertEqual(follow_up.deadline, self.clock() + timedelta(seconds=10))
		self.assertEqual(self.ranking(round_obj), {})

		with self.assertRaises(InvalidInputError):
			self.answer(round_obj, self.p3, 0)
		self.answer(round_obj, self.p2, 1)
		self.answer(round_obj, self.p1, 2)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(self.ranking(round_obj), {1: self.p2.pk, 2: self.p1.pk})
		self.assertEqual(round_obj.number, 1)
		# The first question and its answers are still stored.
		self.assertEqual(first.answers.count(), 3)

	def test_tie_for_second_keeps_first_place(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 0)
		self.answer(round_obj, self.p2, 8, after=1)
		self.answer(round_obj, self.p3, -8)
		rounds.advance_round(round_obj.pk)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk})
		follow_up = self.current(round_obj)
		self.assertEqual(set(follow_up.participants.all()), {self.p2, self.p3})
		self.assertEqual((follow_up.first_place, follow_up.last_place), (2, 2))

		self.answer(round_obj, self.p3, 5)
		self.finish_question(round_obj)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk, 2: self.p3.pk})
		self.assertEqual(round_obj.outcome_reason, REASON_NONE)

	def test_lower_player_is_not_promoted_by_a_non_answering_tied_player(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 1)
		self.answer(round_obj, self.p2, 1)
		self.answer(round_obj, self.p3, 50, after=1)
		rounds.advance_round(round_obj.pk)
		self.answer(round_obj, self.p1, 9)
		self.finish_question(round_obj)
		round_obj.refresh_from_db()
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk})
		self.assertEqual(round_obj.outcome_reason, REASON_INSUFFICIENT_ANSWERS)

	def test_no_answers_asks_the_same_group_again(self):
		round_obj = self.started_round()
		self.finish_question(round_obj)
		follow_up = self.current(round_obj)
		self.assertEqual(set(follow_up.participants.all()), set(self.players))
		self.assertEqual((follow_up.first_place, follow_up.last_place), (1, 2))

	def test_limit_of_three_questions_completes_without_winner(self):
		round_obj = self.started_round()
		for _ in range(3):
			self.finish_question(round_obj)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.status, ROUND_COMPLETED)
		self.assertIsNone(round_obj.winner)
		self.assertIsNotNone(round_obj.completed_at)
		self.assertEqual(round_obj.outcome_reason, REASON_LIMIT_REACHED)
		self.assertEqual(round_obj.questions.count(), 3)
		self.assertFalse(round_obj.questions.exclude(status=QUESTION_COMPLETED).exists())

	def test_winner_on_third_question_is_valid(self):
		round_obj = self.started_round()
		self.finish_question(round_obj)
		self.finish_question(round_obj)
		self.answer(round_obj, self.p2, 0)
		self.answer(round_obj, self.p1, 3)
		self.finish_question(round_obj)  # p3 does not answer: wait for the deadline
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p2)
		self.assertEqual(self.ranking(round_obj), {1: self.p2.pk, 2: self.p1.pk})
		self.assertEqual(round_obj.outcome_reason, REASON_NONE)
		self.assertEqual(round_obj.questions.count(), 3)

	def test_unresolved_second_at_limit_keeps_the_winner(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 0)
		self.answer(round_obj, self.p2, 3, after=1)
		self.answer(round_obj, self.p3, 3)
		rounds.advance_round(round_obj.pk)
		self.finish_question(round_obj)
		self.answer(round_obj, self.p2, 1)
		self.answer(round_obj, self.p3, 1)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk})
		self.assertEqual(round_obj.outcome_reason, REASON_LIMIT_REACHED)


class SmallBankTests(RoundTestBase):
	numeric_count = 1

	def test_missing_initial_question_refuses_creation(self):
		round_obj = self.started_round()
		self.finish_question(round_obj)  # bank exhausted -> completed
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.outcome_reason, REASON_BANK_EXHAUSTED)
		self.assertIsNone(round_obj.winner)

		with self.assertRaises(InvalidStateError) as caught:
			rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(caught.exception.code, 'question_bank_exhausted')
		self.assertEqual(self.game.rounds.count(), 1)

		# After the bank is extended the attempt can be repeated.
		NumericQuestion.objects.create(category=self.numerics[0].category, text='New', correct_answer=1)
		second = rounds.create_city_capture_round(self.game.pk)
		self.assertEqual(second.number, 2)
		self.assertEqual(second.questions.get().text, 'New')


class LimitPrecedenceTests(RoundTestBase):
	numeric_count = 3

	def test_limit_reason_wins_over_exhausted_bank(self):
		round_obj = self.started_round()
		for _ in range(3):
			self.finish_question(round_obj)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.outcome_reason, REASON_LIMIT_REACHED)


class RoundDataTests(RoundTestBase):
	def test_reload_restores_question_deadline_and_ranking(self):
		round_obj = self.started_round()
		self.answer(round_obj, self.p1, 2, after=3)
		state = rounds.get_round_state(round_obj.pk)
		question = self.current(round_obj)
		self.assertEqual(state['current_question']['text'], question.text)
		self.assertEqual(state['current_question']['deadline'], question.deadline)
		self.assertEqual(state['current_question']['remaining_seconds'], 7.0)
		self.assertEqual([a['player_id'] for a in state['current_question']['answers']], [self.p1.pk])

		self.finish_question(round_obj)
		state = rounds.get_round_state(round_obj.pk)
		self.assertIsNone(state['current_question'])
		self.assertEqual(state['ranking'], {1: self.p1.pk})
		self.assertEqual(state['status'], ROUND_COMPLETED)

	def test_editing_the_bank_does_not_change_asked_question(self):
		round_obj = self.started_round()
		question = self.current(round_obj)
		correct = question.correct_answer
		NumericQuestion.objects.filter(pk=question.numeric_question_id).update(
			text='Edited', correct_answer=correct + 1000
		)
		self.answer(round_obj, self.p1, 0)  # uses the stored correct answer
		self.answer(round_obj, self.p2, 1000)
		self.finish_question(round_obj)
		question.refresh_from_db()
		self.assertNotEqual(question.text, 'Edited')
		self.assertEqual(question.correct_answer, correct)
		self.assertEqual(self.ranking(round_obj), {1: self.p1.pk, 2: self.p2.pk})


class RoundConcurrencyTests(RoundTestBase):
	def test_database_allows_only_one_answer_per_player_and_question(self):
		round_obj = self.started_round()
		answer = self.answer(round_obj, self.p1, 0)
		with self.assertRaises(IntegrityError), transaction.atomic():
			RoundAnswer.objects.create(
				question=answer.question, player=self.p1, numeric_value=1, deviation=1,
				submitted_at=self.clock(),
			)
		self.assertEqual(answer.question.answers.count(), 1)
