from unittest import mock

from django.test import TestCase

from games import rounds
from games.errors import InvalidInputError, InvalidStateError, RecordNotFoundError
from games.models import (
	BATTLE,
	CAPITAL_ATTACK,
	CHOICE,
	NUMERIC,
	QUESTION_ACTIVE,
	REASON_BANK_EXHAUSTED,
	REASON_LIMIT_REACHED,
	ROUND_ACTIVE,
	Capital,
	RoundAnswer,
	ScoreEvent,
	Territory,
)
from games.scoring import TERRITORY_INCREMENT, WIN_REWARD
from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion

from .helpers import GameTestMixin


class BattleTestBase(GameTestMixin, TestCase):
	choice_count = 6
	numeric_count = 6

	@classmethod
	def setUpTestData(cls):
		cls.make_users('battle')
		cls.make_bank(numeric=cls.numeric_count, choice=cls.choice_count)

	def setUp(self):
		super().setUp()
		self.game, self.players = self.make_game()
		self.p1, self.p2, self.p3 = self.players
		# Capitals: p1 Скали, p2 Езера, p3 Слънчево. Fill the map:
		# p1 also holds Житно поле and Средец, p2 holds Дунавия, p3 the rest.
		Territory.objects.filter(game=self.game, owner__isnull=True).update(owner=self.p3, score=100)
		self.set_owner(self.game, ['Житно поле', 'Средец'], self.p1, score=100)
		self.set_owner(self.game, ['Дунавия'], self.p2, score=100)

	def battle(self, attacker, target, **kwargs):
		round_obj = rounds.create_battle_round(
			self.game.pk, attacker.pk, self.territory(self.game, target).pk, **kwargs
		)
		rounds.start_round(round_obj.pk)
		return round_obj

	def current(self, round_obj):
		return round_obj.questions.get(status=QUESTION_ACTIVE)

	def choose(self, round_obj, player, correct):
		question = self.current(round_obj)
		option = self.correct_option(question) if correct else self.wrong_option(question)
		self.clock.advance(1)
		return rounds.submit_answer(round_obj.pk, player.pk, option.pk)

	def numeric(self, round_obj, player, offset):
		question = self.current(round_obj)
		self.clock.advance(1)
		return rounds.submit_answer(round_obj.pk, player.pk, question.correct_answer + offset)

	def close(self, round_obj):
		self.clock.advance(10)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		return round_obj

	def score(self, player):
		player.refresh_from_db()
		return player.score


class TargetTests(BattleTestBase):
	def assert_refused(self, error, code, attacker, territory_id, **kwargs):
		with self.assertRaises(error) as caught:
			rounds.create_battle_round(self.game.pk, attacker.pk, territory_id, **kwargs)
		self.assertEqual(caught.exception.code, code)
		self.assertFalse(self.game.rounds.exists())

	def test_invalid_targets(self):
		t = lambda name: self.territory(self.game, name).pk
		self.assert_refused(InvalidInputError, 'own_territory', self.p1, t('Житно поле'))
		self.assert_refused(InvalidInputError, 'territory_not_adjacent', self.p1, t('Слънчево'))
		self.assert_refused(
			InvalidInputError, 'defender_mismatch', self.p1, t('Дунавия'), defender_id=self.p3.pk
		)
		other_game, _ = self.make_game()
		foreign = Territory.objects.get(game=other_game, name='Дунавия').pk
		self.assert_refused(InvalidInputError, 'territory_not_in_game', self.p1, foreign)
		self.assert_refused(RecordNotFoundError, 'territory_not_found', self.p1, 999999)

	def test_free_target_is_refused(self):
		Territory.objects.filter(game=self.game, name='Дунавия').update(owner=None)
		self.assert_refused(
			InvalidInputError, 'territory_free', self.p1, self.territory(self.game, 'Дунавия').pk
		)

	def test_battles_wait_for_the_full_map(self):
		Territory.objects.filter(game=self.game, name='Мадара').update(owner=None)
		self.assert_refused(
			InvalidStateError, 'conquest_not_finished', self.p1, self.territory(self.game, 'Дунавия').pk
		)

	def test_kind_and_participants(self):
		round_obj = rounds.create_battle_round(
			self.game.pk, self.p1.pk, self.territory(self.game, 'Дунавия').pk, defender_id=self.p2.pk
		)
		self.assertEqual(round_obj.kind, BATTLE)
		self.assertEqual((round_obj.attacker, round_obj.defender), (self.p1, self.p2))
		self.assertEqual(set(p.player for p in round_obj.participants.all()), {self.p1, self.p2})
		question = round_obj.questions.get()
		self.assertEqual(question.question_type, CHOICE)
		self.assertEqual(len(question.options), 4)


class AnswerTests(BattleTestBase):
	def test_option_from_another_question_is_invalid(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		question = self.current(round_obj)
		foreign = AnswerOption.objects.exclude(question=question.choice_question).first()
		with self.assertRaises(InvalidInputError) as caught:
			rounds.submit_answer(round_obj.pk, self.p1.pk, foreign.pk)
		self.assertEqual(caught.exception.code, 'option_not_in_question')
		self.assertFalse(RoundAnswer.objects.exists())
		answer = self.choose(round_obj, self.p1, correct=True)
		self.assertTrue(answer.is_correct)

	def test_third_player_cannot_answer(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		with self.assertRaises(InvalidInputError) as caught:
			self.choose(round_obj, self.p3, correct=True)
		self.assertEqual(caught.exception.code, 'not_a_participant')


class OutcomeTests(BattleTestBase):
	def test_single_correct_attacker_captures(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p2, correct=False)
		self.choose(round_obj, self.p1, correct=True)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p1)
		target = self.territory(self.game, 'Дунавия')
		self.assertEqual(target.owner, self.p1)
		self.assertEqual(target.score, 100 + TERRITORY_INCREMENT)
		self.assertEqual(self.score(self.p1), WIN_REWARD + 200)
		self.assertEqual(self.score(self.p2), 0)

	def test_single_correct_defender_defends(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p2, correct=True)
		self.choose(round_obj, self.p1, correct=False)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p2)
		target = self.territory(self.game, 'Дунавия')
		self.assertEqual((target.owner, target.score), (self.p2, 100))
		self.assertEqual(self.score(self.p2), WIN_REWARD)
		self.assertEqual(self.score(self.p1), 0)

	def test_two_correct_continue_with_numeric_and_numeric_decides(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)  # faster, but speed does not matter here
		self.choose(round_obj, self.p2, correct=True)
		rounds.advance_round(round_obj.pk)
		follow_up = self.current(round_obj)
		self.assertEqual(follow_up.question_type, NUMERIC)
		self.assertEqual(follow_up.sequence, 2)
		self.assertEqual(set(follow_up.participants.all()), {self.p1, self.p2})
		self.assertEqual(follow_up.started_at, self.clock())

		self.numeric(round_obj, self.p1, 20)
		self.numeric(round_obj, self.p2, -3)
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.winner, self.p2)
		self.assertEqual(self.territory(self.game, 'Дунавия').owner, self.p2)

	def test_zero_correct_asks_a_new_choice_question(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		first = self.current(round_obj)
		self.choose(round_obj, self.p1, correct=False)  # wrong is no better than silence
		self.close(round_obj)
		follow_up = self.current(round_obj)
		self.assertEqual(follow_up.question_type, CHOICE)
		self.assertNotEqual(follow_up.choice_question_id, first.choice_question_id)
		self.assertEqual(set(follow_up.participants.all()), {self.p1, self.p2})

	def test_numeric_tie_continues_with_numeric_and_third_question_wins(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)
		self.choose(round_obj, self.p2, correct=True)
		rounds.advance_round(round_obj.pk)
		self.close(round_obj)  # no numeric answer -> numeric again, not choice
		third = self.current(round_obj)
		self.assertEqual((third.sequence, third.question_type), (3, NUMERIC))
		self.numeric(round_obj, self.p1, 1)
		self.close(round_obj)
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(round_obj.questions.count(), 3)

	def test_limit_reached_without_winner_changes_nothing(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		for _ in range(3):
			self.close(round_obj)
		self.assertIsNone(round_obj.winner)
		self.assertEqual(round_obj.outcome_reason, REASON_LIMIT_REACHED)
		self.assertEqual(self.territory(self.game, 'Дунавия').owner, self.p2)
		self.assertFalse(ScoreEvent.objects.exists())

	def test_capital_attack_rewards_without_changing_the_capital(self):
		capital = Capital.objects.get(player=self.p2)
		round_obj = self.battle(self.p1, 'Езера')
		self.assertEqual(round_obj.kind, CAPITAL_ATTACK)
		self.choose(round_obj, self.p1, correct=True)
		self.close(round_obj)
		self.assertEqual(round_obj.winner, self.p1)
		self.assertEqual(self.score(self.p1), WIN_REWARD)
		capital.refresh_from_db()
		territory = self.territory(self.game, 'Езера')
		self.assertEqual((capital.player, capital.territory, capital.health), (self.p2, territory, 3))
		self.assertEqual((territory.owner, territory.score), (self.p2, 0))


class IntegrityTests(BattleTestBase):
	def test_repeated_completion_repeats_nothing(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)
		self.close(round_obj)
		with self.assertRaises(InvalidStateError):
			rounds.advance_round(round_obj.pk)
		self.assertEqual(ScoreEvent.objects.filter(round=round_obj).count(), 2)
		self.assertEqual(self.territory(self.game, 'Дунавия').score, 200)

	def test_changed_target_owner_refuses_the_result(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)
		Territory.objects.filter(game=self.game, name='Дунавия').update(owner=self.p3)
		self.clock.advance(10)
		with self.assertRaises(InvalidStateError) as caught:
			rounds.advance_round(round_obj.pk)
		self.assertEqual(caught.exception.code, 'target_changed')
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.status, ROUND_ACTIVE)
		self.assertEqual(RoundAnswer.objects.filter(question__round=round_obj).count(), 1)
		self.assertFalse(ScoreEvent.objects.exists())
		self.assertEqual(self.score(self.p1), 0)

	def test_error_while_applying_rolls_back(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)
		self.clock.advance(10)
		with mock.patch('games.scoring.capture', side_effect=RuntimeError('boom')):
			with self.assertRaises(RuntimeError):
				rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.assertEqual(round_obj.status, ROUND_ACTIVE)
		self.assertEqual(self.current(round_obj).sequence, 1)
		self.assertEqual(self.score(self.p1), 0)
		self.assertEqual(self.territory(self.game, 'Дунавия').owner, self.p2)
		rounds.advance_round(round_obj.pk)  # the retry completes once
		self.assertEqual(self.territory(self.game, 'Дунавия').owner, self.p1)

	def test_stale_second_advance_creates_only_one_follow_up(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.choose(round_obj, self.p1, correct=True)
		self.choose(round_obj, self.p2, correct=True)
		rounds.advance_round(round_obj.pk)
		with self.assertRaises(InvalidStateError):
			rounds.advance_round(round_obj.pk)  # new question is still open
		self.assertEqual(round_obj.questions.count(), 2)


class NoChoiceQuestionTests(BattleTestBase):
	choice_count = 0

	def test_missing_initial_question_refuses_creation(self):
		with self.assertRaises(InvalidStateError) as caught:
			rounds.create_battle_round(self.game.pk, self.p1.pk, self.territory(self.game, 'Дунавия').pk)
		self.assertEqual(caught.exception.code, 'question_bank_exhausted')
		self.assertFalse(self.game.rounds.exists())


class ExhaustedBankTests(BattleTestBase):
	choice_count = 1

	def test_exhausted_bank_ends_without_winner(self):
		round_obj = self.battle(self.p1, 'Дунавия')
		self.close(round_obj)
		self.assertIsNone(round_obj.winner)
		self.assertEqual(round_obj.outcome_reason, REASON_BANK_EXHAUSTED)


class QuestionHistoryTests(BattleTestBase):
	def test_same_ids_in_both_models_stay_distinct(self):
		category = Category.objects.create(name='Same ids')
		shared_id = 500
		choice = ChoiceQuestion.objects.create(pk=shared_id, category=category, text='Choice 500')
		for index in range(4):
			AnswerOption.objects.create(question=choice, text=str(index), is_correct=index == 0)
		NumericQuestion.objects.create(pk=shared_id, category=category, text='Numeric 500', correct_answer=5)
		ChoiceQuestion.objects.exclude(pk=shared_id).delete()
		NumericQuestion.objects.exclude(pk=shared_id).delete()

		round_obj = self.battle(self.p1, 'Дунавия')
		first_answers = [
			self.choose(round_obj, self.p1, correct=True),
			self.choose(round_obj, self.p2, correct=True),
		]
		rounds.advance_round(round_obj.pk)
		self.numeric(round_obj, self.p2, 0)
		self.close(round_obj)

		state = rounds.get_round_state(round_obj.pk)
		steps = [(q['type'], q['bank_question_id'], q['text']) for q in state['questions']]
		self.assertEqual(steps, [(CHOICE, 500, 'Choice 500'), (NUMERIC, 500, 'Numeric 500')])
		self.assertEqual([len(q['answers']) for q in state['questions']], [2, 1])
		first = round_obj.questions.get(sequence=1)
		self.assertEqual(list(first.answers.order_by('submitted_at')), first_answers)
		self.assertTrue(all(answer.is_correct for answer in first.answers.all()))
		self.assertEqual(state['winner_id'], self.p2.pk)
