"""Errors raised by the game operations (rounds, captures, battles).

Every refusal is a ``GameOperationError`` (a Django ``ValidationError``) with a
stable ``code``. The subclass tells the caller *which kind* of refusal it is:

* ``InvalidInputError``   - the arguments themselves are wrong (bad value,
  option from another question, territory of another game, ...).
* ``InvalidStateError``   - the arguments are fine, but the game/round is not
  in a state that allows the operation (deadline passed, already answered,
  round completed, ...).
* ``RecordNotFoundError`` - a referenced id does not exist.

A refused operation never leaves a partial change in the database.
"""

from django.core.exceptions import ValidationError


class GameOperationError(ValidationError):
	category = 'error'

	def __init__(self, message, code):
		super().__init__(message, code=code)


class InvalidInputError(GameOperationError):
	category = 'invalid_input'


class InvalidStateError(GameOperationError):
	category = 'invalid_state'


class RecordNotFoundError(GameOperationError):
	category = 'not_found'
