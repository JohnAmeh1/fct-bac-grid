from django.contrib import messages
from django.shortcuts import redirect

from .models import SiteConfiguration

# Paths that must keep working even while the site is in maintenance mode:
# admins need to be able to log in and turn maintenance mode back off, and
# static/media assets must keep loading.
_MAINTENANCE_EXEMPT_PREFIXES = (
    '/admin/',
    '/accounts/login/',
    '/accounts/logout/',
    '/management/configuration/',
    '/static/',
    '/media/',
)


class MaintenanceModeMiddleware:
    """
    Enforces SiteConfiguration.maintenance_mode as a genuine "read-only"
    mode: while active, any request that would change data (a non-GET/HEAD
    request) is rejected for everyone except admins. Admins are always
    exempt so they can keep working and turn maintenance mode back off.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not any(request.path.startswith(p) for p in _MAINTENANCE_EXEMPT_PREFIXES):
                profile = getattr(request.user, 'userprofile', None)
                is_admin = bool(profile and profile.user_type == 'admin')
                if not is_admin and SiteConfiguration.get_config().maintenance_mode:
                    messages.error(
                        request,
                        'The site is currently in maintenance mode. Changes are temporarily disabled — please try again shortly.'
                    )
                    return redirect(request.META.get('HTTP_REFERER') or 'home')
        return self.get_response(request)
