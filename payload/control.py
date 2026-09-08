"""Remote control channel for the phone page.

The phone must keep the GPS page in the foreground, or the position stops
updating. Thus it cannot open a second page for controls. The controls live on
the GPS page instead, and their commands reach this payload through the GPS
server, which forwards them here. Refer to the README.

The web server runs in its own thread. It must not change the scan state or the
scan threads directly, because the main loop owns them. Thus a command goes into
a queue, and the main loop takes it out and runs it on its own thread. The web
server reads a status snapshot that the main loop publishes, and touches neither
the scan nor the database.

A control command needs a token. Control is off when no token is set, thus the
default state is safe: a fresh install accepts no commands until the operator
sets control_token in settings.json.
"""

import queue
import threading

MAX_QUEUED = 16


class ControlChannel:
    def __init__(self, token=""):
        self._commands = queue.Queue(maxsize=MAX_QUEUED)
        self._status = {}
        self._status_lock = threading.Lock()
        self._token = token or ""

    @property
    def enabled(self):
        """Control is enabled only when a token is set."""
        return bool(self._token)

    def authorised(self, token):
        """Report whether a token is correct. False when control is off."""
        if not self._token:
            return False
        return _constant_time_equal(token or "", self._token)

    # Commands: the web thread submits, the main loop drains.

    def submit(self, action, params=None):
        """Queue a command. Return False if the queue is full."""
        try:
            self._commands.put_nowait({"action": action, "params": params or {}})
            return True
        except queue.Full:
            return False

    def drain(self):
        """Take every queued command. The main loop calls this."""
        commands = []
        while True:
            try:
                commands.append(self._commands.get_nowait())
            except queue.Empty:
                return commands

    # Status: the main loop publishes, the web thread reads.

    def publish(self, status):
        """Store the latest status snapshot."""
        with self._status_lock:
            self._status = dict(status)

    def snapshot(self):
        """Return the latest status snapshot."""
        with self._status_lock:
            return dict(self._status)


def _constant_time_equal(a, b):
    """Compare two strings in a time that does not depend on where they differ.

    A plain == returns early at the first wrong character, which tells an
    attacker how much of the token is correct. This does not. The payload does
    not ship the hmac module on every build, thus this is written by hand.
    """
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0
