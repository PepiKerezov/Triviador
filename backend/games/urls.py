from django.urls import path

from .views import MatchmakingView

urlpatterns = [
	path('matchmaking/', MatchmakingView.as_view(), name='matchmaking'),
]
