from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import (
	Capital,
	CaptureRight,
	Game,
	GamePlayer,
	Round,
	RoundAnswer,
	RoundQuestion,
	ScoreEvent,
	Territory,
)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
	list_display = ('id', 'created_by', 'status', 'created_at', 'started_at', 'finished_at')
	list_filter = ('status',)
	readonly_fields = ('status', 'started_at', 'finished_at')


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
	list_display = ('game', 'user', 'player_order', 'score', 'is_active', 'joined_at')
	list_filter = ('is_active',)

	def has_delete_permission(self, request, obj=None):
		return obj is None or obj.game.status == 'waiting'

	def save_model(self, request, obj, form, change):
		if obj.game.status != 'waiting':
			raise ValidationError('Players cannot be changed after game initialization.')
		super().save_model(request, obj, form, change)


class ReadOnlyHistoryAdmin(admin.ModelAdmin):
	"""Round history is written only by games.rounds / games.capture."""

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


@admin.register(Round)
class RoundAdmin(ReadOnlyHistoryAdmin):
	list_display = (
		'game', 'number', 'kind', 'status', 'winner', 'outcome_reason', 'started_at', 'completed_at'
	)
	list_filter = ('status', 'kind', 'outcome_reason')


@admin.register(RoundQuestion)
class RoundQuestionAdmin(ReadOnlyHistoryAdmin):
	list_display = ('round', 'sequence', 'question_type', 'status', 'started_at', 'deadline')
	list_filter = ('question_type', 'status')


@admin.register(RoundAnswer)
class RoundAnswerAdmin(ReadOnlyHistoryAdmin):
	list_display = ('question', 'player', 'numeric_value', 'selected_option', 'is_correct', 'submitted_at')
	list_filter = ('is_correct',)


@admin.register(CaptureRight)
class CaptureRightAdmin(ReadOnlyHistoryAdmin):
	list_display = ('round', 'player', 'order', 'allowed', 'used')


@admin.register(ScoreEvent)
class ScoreEventAdmin(ReadOnlyHistoryAdmin):
	list_display = (
		'round', 'player', 'kind', 'territory', 'points',
		'player_score_before', 'player_score_after', 'calculation',
	)
	list_filter = ('kind',)


@admin.register(Territory)
class TerritoryAdmin(admin.ModelAdmin):
	list_display = ('game', 'name', 'slug', 'owner', 'score', 'neighbor_list')
	search_fields = ('name', 'slug')
	list_filter = ('game', 'owner')
	readonly_fields = ('game', 'name', 'slug', 'owner', 'neighbors')
	fields = ('game', 'name', 'slug', 'owner', 'score', 'neighbors')

	def neighbor_list(self, obj):
		return ', '.join(neighbor.name for neighbor in obj.neighbors.all())

	neighbor_list.short_description = 'Neighbors'

	def has_add_permission(self, request):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


@admin.register(Capital)
class CapitalAdmin(admin.ModelAdmin):
	list_display = ('player', 'territory', 'health')
	search_fields = ('player__user__username', 'territory__name')
	list_filter = ('territory__game',)
	readonly_fields = ('player', 'territory')
	fields = ('player', 'territory', 'health')

	def has_add_permission(self, request):
		return False

	def has_delete_permission(self, request, obj=None):
		return False