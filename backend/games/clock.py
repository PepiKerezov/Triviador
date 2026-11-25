"""Trusted application time.

Operations read the moment from here, never from caller input. Tests patch
``games.clock.now`` to control time without real waiting.
"""

from django.utils import timezone


def now():
	return timezone.now()
