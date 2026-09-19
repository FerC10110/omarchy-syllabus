"""The one exception every command raises, carrying the exit code to use."""

GENERAL = 1
USAGE = 2
UNKNOWN = 3
OFFLINE = 4
PLAYER = 5
READILY = 6

# Reasons: fixed words an error's JSON can carry for the window to match on.
NOTE_CHANGED = "noteChanged"


class SyllabusError(Exception):
    """`reason`, when set, is a fixed word the window can match on (the message is for people)."""

    def __init__(self, message, code=GENERAL, reason=None):
        super().__init__(message)
        self.code = code
        self.reason = reason
