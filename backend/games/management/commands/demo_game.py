"""Play a short demo game on the local database and print the records.

    python manage.py loaddata questions/question_bank.json
    python manage.py demo_game

Creates three demo users and a new game, plays city_capture rounds until the
map is full (scripted answers, every player answers so no waiting is needed),
then one battle where both players answer the choice question correctly and a
numeric question decides.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from games import rounds
from games.capture import capture_territory, eligible_territories, is_conquest_over, next_capture_right
from games.models import QUESTION_ACTIVE, Capital, Game, GamePlayer, ScoreEvent, Territory
from games.services import initialize_game


class Command(BaseCommand):
	help = 'Play a scripted demo game (city captures and one battle) on the local database.'

	def handle(self, *args, **options):
		game, players = self._create_game()
		self.stdout.write(f'Game {game.pk}: players {[p.user.username for p in players]}')
		for capital in Capital.objects.filter(player__game=game).select_related('territory', 'player__user'):
			self.stdout.write(f'  capital {capital.territory.name} -> {capital.player.user.username}')

		while not is_conquest_over(game):
			self._play_city_capture(game, players)
		self._play_battle(game, players)

		self.stdout.write('\nFinal scores:')
		for player in GamePlayer.objects.filter(game=game).select_related('user'):
			owned = Territory.objects.filter(owner=player).count()
			self.stdout.write(f'  {player.user.username}: {player.score} points, {owned} territories')

	def _create_game(self):
		model = get_user_model()
		users = []
		for name in ('demo_ana', 'demo_boris', 'demo_vera'):
			user, _ = model.objects.get_or_create(username=name, defaults={'email': f'{name}@example.com'})
			users.append(user)
		game = Game.objects.create(created_by=users[0], status='waiting')
		players = [
			GamePlayer.objects.create(game=game, user=user, player_order=index)
			for index, user in enumerate(users, start=1)
		]
		initialize_game(game.pk)
		game.refresh_from_db()
		return game, players

	def _answer_all(self, round_obj, ranking, offsets):
		question = round_obj.questions.get(status=QUESTION_ACTIVE)
		for player, offset in zip(ranking, offsets):
			rounds.submit_answer(round_obj.pk, player.pk, question.correct_answer + offset)
		return question

	def _play_city_capture(self, game, players):
		try:
			round_obj = rounds.create_city_capture_round(game.pk)
		except Exception as exc:  # e.g. question_bank_exhausted
			raise CommandError(f'Cannot create a round: {exc}') from exc
		rounds.start_round(round_obj.pk)
		shift = round_obj.number % 3
		ranking = players[shift:] + players[:shift]
		question = self._answer_all(round_obj, ranking, (2, -9, 40))
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.stdout.write(
			f'\nRound {round_obj.number} ({round_obj.kind}), free={round_obj.free_territories_at_creation}, '
			f'question "{question.text}" = {question.correct_answer}'
		)
		for answer in question.answers.select_related('player__user').order_by('deviation', 'submitted_at'):
			self.stdout.write(
				f'  {answer.player.user.username}: {answer.numeric_value} (deviation {answer.deviation})'
			)
		state = rounds.get_round_state(round_obj.pk)
		self.stdout.write(f'  ranking {state["ranking"]}, winner {round_obj.winner_id}, reason "{round_obj.outcome_reason}"')

		while (right := next_capture_right(game)) is not None:
			target = eligible_territories(game, right.player).order_by('name').first()
			result = capture_territory(game.pk, right.player_id, target.pk)
			event = ScoreEvent.objects.filter(territory_id=target.pk, round=round_obj).get()
			self.stdout.write(
				f'  pick #{right.order} {right.player.user.username} -> {target.name}: {event.calculation}'
				f' (rights left {result.remaining_rights})'
			)

	def _play_battle(self, game, players):
		for attacker in players:
			target = (
				Territory.objects.filter(game=game, capital__isnull=True, neighbors__owner=attacker)
				.exclude(owner=attacker)
				.order_by('name')
				.first()
			)
			if target is not None:
				break
		defender = target.owner
		round_obj = rounds.create_battle_round(game.pk, attacker.pk, target.pk)
		rounds.start_round(round_obj.pk)
		self.stdout.write(
			f'\nRound {round_obj.number} ({round_obj.kind}): {attacker.user.username} attacks '
			f'{target.name} (score {target.score}) of {defender.user.username}'
		)
		choice = round_obj.questions.get(status=QUESTION_ACTIVE)
		correct = choice.choice_question.answer_options.get(is_correct=True)
		for player in (attacker, defender):
			rounds.submit_answer(round_obj.pk, player.pk, correct.pk)
		rounds.advance_round(round_obj.pk)
		self.stdout.write(f'  Q1 choice "{choice.text}" (bank id {choice.choice_question_id}): both correct')
		numeric = self._answer_all(round_obj, [attacker, defender], (1, -6))
		rounds.advance_round(round_obj.pk)
		round_obj.refresh_from_db()
		self.stdout.write(
			f'  Q2 numeric "{numeric.text}" (bank id {numeric.numeric_question_id}) = {numeric.correct_answer}'
		)
		for answer in numeric.answers.select_related('player__user'):
			self.stdout.write(f'    {answer.player.user.username}: {answer.numeric_value} (deviation {answer.deviation})')
		target.refresh_from_db()
		self.stdout.write(
			f'  winner {round_obj.winner.user.username}; {target.name} owner '
			f'{target.owner.user.username}, score {target.score}'
		)
		for event in round_obj.score_events.select_related('player__user'):
			self.stdout.write(f'    {event.kind} {event.player.user.username}: {event.calculation}')
