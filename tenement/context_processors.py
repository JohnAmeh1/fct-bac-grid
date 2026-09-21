from .models import SiteConfiguration


def site_configuration(request):
    """Expose the singleton configuration to every template."""
    return {'site_config': SiteConfiguration.get_config()}