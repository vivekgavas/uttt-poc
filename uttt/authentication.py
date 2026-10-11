"""
API key authentication for the UTTT platform APIs.

Platform management endpoints (products, test cases, workflows) require
the X-Platform-Api-Key header matching the PLATFORM_API_KEY env var.

The callback endpoint (/api/execution-events/) uses a different, per-product
key validated inline in the view — not through this class.
"""
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class PlatformPrincipal:
    """Minimal principal object returned by PlatformApiKeyAuthentication."""
    is_authenticated = True
    is_anonymous = False
    pk = None

    def __str__(self):
        return 'platform-api-key'


class PlatformApiKeyAuthentication(BaseAuthentication):
    """
    Reads the X-Platform-Api-Key header and validates it against
    settings.PLATFORM_API_KEY.

    Returns (PlatformPrincipal, None) on success.
    Returns None if the header is absent (allows other auth methods to run).
    Raises AuthenticationFailed if the header is present but wrong.
    """

    def authenticate(self, request):
        key = request.headers.get('X-Platform-Api-Key')
        if key is None:
            return None
        expected = getattr(settings, 'PLATFORM_API_KEY', None)
        if not expected:
            raise AuthenticationFailed('Platform API key is not configured on this server.')
        if key != expected:
            raise AuthenticationFailed('Invalid platform API key.')
        return (PlatformPrincipal(), None)

    def authenticate_header(self, request):
        return 'X-Platform-Api-Key'
