"""
Thread-local storage for current request user.

Used by model-level security checks (save/signal) to identify the
calling user without threading through every function signature.

Inspired by Django's own thread-local pattern for get_current_user().
"""

import threading

_thread_locals = threading.local()


def get_current_user():
    """Return the currently authenticated user, or None."""
    return getattr(_thread_locals, "user", None)


def set_current_user(user):
    """Set the current user on this thread."""
    _thread_locals.user = user


def clear_current_user():
    """Remove the current user from this thread."""
    _thread_locals.user = None
