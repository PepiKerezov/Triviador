from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)
	search_fields = ('name',)


class AnswerOptionInlineFormSet(BaseInlineFormSet):
	def clean(self):
		super().clean()
		if any(self.errors):
			return

		active_forms = [form for form in self.forms if not form.cleaned_data.get('DELETE', False)]
		if len(active_forms) != 4:
			return
		if sum(form.cleaned_data.get('is_correct', False) for form in active_forms) != 1:
			raise ValidationError('A choice question must have exactly one correct option.')


class AnswerOptionInline(admin.TabularInline):
	model = AnswerOption
	formset = AnswerOptionInlineFormSet
	extra = 4
	min_num = 4
	max_num = 4
	validate_min = True
	validate_max = True


@admin.register(ChoiceQuestion)
class ChoiceQuestionAdmin(admin.ModelAdmin):
	list_display = ('text', 'category')
	list_filter = ('category',)
	search_fields = ('text',)
	inlines = (AnswerOptionInline,)


@admin.register(NumericQuestion)
class NumericQuestionAdmin(admin.ModelAdmin):
	list_display = ('text', 'category', 'correct_answer')
	list_filter = ('category',)
	search_fields = ('text',)