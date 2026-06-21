"""
Middleware that captures request.user into thread-local storage
so that model-layer security checks can identify the acting user.
"""

from .thread_local import set_current_user, clear_current_user


class RequestUserMiddleware:
    """Store request.user in thread-local for the duration of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_user(getattr(request, "user", None))
        try:
            response = self.get_response(request)
        finally:
            clear_current_user()
        return response
