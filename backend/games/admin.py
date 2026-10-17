from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Capital, Game, GamePlayer, Round, RoundAnswer, Territory


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


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
	list_display = ('game', 'number', 'status', 'question_type', 'started_at', 'finished_at')
	list_filter = ('status', 'question_type')


@admin.register(RoundAnswer)
class RoundAnswerAdmin(admin.ModelAdmin):
	list_display = ('round', 'player', 'is_correct', 'points_awarded', 'submitted_at')
	list_filter = ('is_correct',)


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