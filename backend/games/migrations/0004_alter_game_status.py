from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('games', '0003_alter_territory_slug'),
	]

	operations = [
		migrations.AlterField(
			model_name='game',
			name='status',
			field=models.CharField(
				choices=[
					('waiting', 'Waiting'),
					('active', 'Active'),
					('in_progress', 'In Progress'),
					('finished', 'Finished'),
					('cancelled', 'Cancelled'),
				],
				max_length=20,
			),
		),
	]