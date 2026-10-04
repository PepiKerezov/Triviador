from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


class QuestionModelTests(TestCase):
	def setUp(self):
		self.category = Category.objects.create(name='Наука')

	def create_choice_question(self, option_count=4, correct_count=1):
		question = ChoiceQuestion.objects.create(
			category=self.category,
			text='Кой е химичният символ на златото?',
		)
		for index in range(option_count):
			AnswerOption.objects.create(
				question=question,
				text=f'Отговор {index + 1}',
				is_correct=index < correct_count,
			)
		return question

	def test_category_name_is_required_and_unique(self):
		self.assertEqual(str(self.category), 'Наука')
		with self.assertRaises(IntegrityError):
			Category.objects.create(name='Наука')

	def test_choice_question_requires_four_options_and_one_correct_option(self):
		valid_question = self.create_choice_question()
		valid_question.full_clean()

		for option_count, correct_count in ((3, 1), (5, 1), (4, 0), (4, 2)):
			with self.subTest(option_count=option_count, correct_count=correct_count):
				question = self.create_choice_question(option_count, correct_count)
				with self.assertRaises(ValidationError):
					question.full_clean()

	def test_numeric_question_has_integer_correct_answer(self):
		question = NumericQuestion.objects.create(
			category=self.category,
			text='Колко е две плюс две?',
			correct_answer=4,
		)
		question.full_clean()
		self.assertEqual(question.correct_answer, 4)

	def test_deleting_choice_question_deletes_options(self):
		question = self.create_choice_question()
		question_id = question.id
		question.delete()
		self.assertFalse(AnswerOption.objects.filter(question_id=question_id).exists())

	def test_category_with_questions_is_protected(self):
		self.create_choice_question()
		with self.assertRaises(ProtectedError):
			self.category.delete()