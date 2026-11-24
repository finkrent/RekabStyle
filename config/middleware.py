import ipaddress

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class TrustedProxyClientIpMiddleware(MiddlewareMixin):
    """Replace REMOTE_ADDR only when the direct peer is a configured proxy.

    The proxy must overwrite X-Real-IP (not append to it). Untrusted peers
    cannot influence the address used by IP-based abuse controls.
    """

    def process_request(self, request):
        peer = self._parse_ip(request.META.get("REMOTE_ADDR", ""))
        if peer is None or not self._is_trusted_proxy(peer):
            return None

        forwarded_ip = self._parse_ip(request.META.get("HTTP_X_REAL_IP", ""))
        if forwarded_ip is not None:
            request.META["REMOTE_ADDR"] = str(forwarded_ip)
        return None

    @staticmethod
    def _parse_ip(value):
        try:
            return ipaddress.ip_address(value)
        except ValueError:
            return None

    @classmethod
    def _is_trusted_proxy(cls, peer):
        for network in settings.TRUSTED_PROXY_IPS:
            try:
                if peer in ipaddress.ip_network(network, strict=False):
                    return True
            except ValueError:
                continue
        return False
