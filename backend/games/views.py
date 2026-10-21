from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import MatchmakingError, join_matchmaking, leave_matchmaking


class MatchmakingView(APIView):
	permission_classes = (permissions.IsAuthenticated,)

	def post(self, request):
		try:
			result = join_matchmaking(request.user)
		except MatchmakingError as exc:
			return Response(
				{'errors': {'non_field_errors': exc.messages}, 'code': exc.code},
				status=status.HTTP_400_BAD_REQUEST,
			)
		return Response(
			{
				'game_id': result.game_id,
				'selected_user_ids': result.selected_user_ids,
			},
			status=status.HTTP_201_CREATED,
		)

	def delete(self, request):
		leave_matchmaking(request.user)
		return Response(status=status.HTTP_204_NO_CONTENT)
