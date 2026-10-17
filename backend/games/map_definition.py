from itertools import combinations

from django.core.exceptions import ValidationError


PROJECT_MAP = {
	'Скали': ('Дунавия', 'Житно поле'),
	'Дунавия': ('Скали', 'Житно поле', 'Левента'),
	'Житно поле': ('Скали', 'Дунавия', 'Левента', 'Балкания'),
	'Левента': ('Дунавия', 'Житно поле', 'Балкания', 'Царево'),
	'Балкания': ('Житно поле', 'Левента', 'Царево', 'Мадара', 'Средец'),
	'Царево': ('Левента', 'Балкания', 'Мадара', 'Калиакра'),
	'Мадара': ('Балкания', 'Царево', 'Калиакра', 'Пеликания'),
	'Пеликания': ('Мадара', 'Калиакра', 'Средец', 'Езера'),
	'Калиакра': ('Царево', 'Мадара', 'Пеликания'),
	'Средец': ('Балкания', 'Пеликания', 'Езера', 'Пирина'),
	'Езера': ('Пеликания', 'Средец', 'Пирина', 'Розова долина'),
	'Пирина': ('Средец', 'Езера', 'Розова долина', 'Чуден край'),
	'Розова долина': ('Езера', 'Пирина', 'Чуден край', 'Златен грозд'),
	'Чуден край': ('Пирина', 'Розова долина', 'Златен грозд', 'Кукери'),
	'Златен грозд': ('Розова долина', 'Чуден край', 'Кукери', 'Каракачан'),
	'Кукери': ('Чуден край', 'Златен грозд', 'Каракачан', 'Слънчево'),
	'Каракачан': ('Златен грозд', 'Кукери', 'Слънчево'),
	'Слънчево': ('Кукери', 'Каракачан'),
}


def slug_for_name(name):
	return name.strip().lower().replace(' ', '-')


def validate_project_map():
	if len(PROJECT_MAP) not in (9, 12, 15, 18, 21) or len(PROJECT_MAP) % 3:
		raise ValidationError('Project map must contain 9, 12, 15, 18, or 21 territories.')
	if len({slug_for_name(name) for name in PROJECT_MAP}) != len(PROJECT_MAP):
		raise ValidationError('Project map slugs must be unique.')
	for name, neighbors in PROJECT_MAP.items():
		if not name.strip() or len(set(neighbors)) != len(neighbors):
			raise ValidationError('Project map names and neighbors must be non-empty and unique.')
		if name in neighbors or len(neighbors) < 2 or any(neighbor not in PROJECT_MAP for neighbor in neighbors):
			raise ValidationError('Project map contains an invalid neighbor.')
		for neighbor in neighbors:
			if name not in PROJECT_MAP[neighbor]:
				raise ValidationError('Project map neighbors must be symmetric.')
	visited = set()
	frontier = [next(iter(PROJECT_MAP))]
	while frontier:
		name = frontier.pop()
		if name in visited:
			continue
		visited.add(name)
		frontier.extend(neighbor for neighbor in PROJECT_MAP[name] if neighbor not in visited)
	if len(visited) != len(PROJECT_MAP):
		raise ValidationError('Project map must be connected.')
	for first, second, third in combinations(PROJECT_MAP, 3):
		if (
			second not in PROJECT_MAP[first]
			and third not in PROJECT_MAP[first]
			and third not in PROJECT_MAP[second]
		):
			return
	raise ValidationError('Project map must contain three pairwise non-neighboring territories.')


def validate_game_map(game):
	from .models import Territory

	territories = list(Territory.objects.filter(game=game).prefetch_related('neighbors'))
	if len(territories) != len(PROJECT_MAP):
		raise ValidationError('Game map does not contain the complete project map.')
	by_name = {territory.name: territory for territory in territories}
	if set(by_name) != set(PROJECT_MAP) or any(
		territory.slug != slug_for_name(territory.name) for territory in territories
	):
		raise ValidationError('Game map names or slugs do not match the project map.')
	for name, expected_neighbors in PROJECT_MAP.items():
		actual_neighbors = {neighbor.name for neighbor in by_name[name].neighbors.all()}
		if actual_neighbors != set(expected_neighbors):
			raise ValidationError('Game map neighbors do not match the project map.')