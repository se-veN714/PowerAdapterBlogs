from .policies import can_view_security_operations


def operations_context(request):
    return {
        "can_access_security_operations": can_view_security_operations(
            request.user
        )
    }
