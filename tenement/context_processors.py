from .models import SiteConfiguration


def site_configuration(request):
    """Expose the singleton configuration to every template."""
    dark_mode = (
        request.user.is_authenticated
        and hasattr(request.user, 'userprofile')
        and request.user.userprofile.dark_mode
    )
    return {
        'site_config': SiteConfiguration.get_config(),
        'dark_mode_enabled': dark_mode,
    }