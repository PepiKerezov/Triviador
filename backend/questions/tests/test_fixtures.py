from django.core.management import call_command
from django.test import TestCase

from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


class QuestionFixtureTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		call_command('loaddata', 'questions/question_bank.json', verbosity=0)

	def test_fixture_has_expected_counts(self):
		self.assertEqual(Category.objects.count(), 6)
		self.assertEqual(ChoiceQuestion.objects.count(), 12)
		self.assertEqual(AnswerOption.objects.count(), 48)
		self.assertEqual(NumericQuestion.objects.count(), 12)

	def test_fixture_choice_questions_have_four_options_and_one_correct(self):
		for question in ChoiceQuestion.objects.all():
			with self.subTest(question=question.pk):
				self.assertEqual(question.answer_options.count(), 4)
				self.assertEqual(
					question.answer_options.filter(is_correct=True).count(),
					1,
				)

	def test_fixture_numeric_questions_have_correct_answers(self):
		self.assertTrue(
			all(question.correct_answer is not None for question in NumericQuestion.objects.all())
		)