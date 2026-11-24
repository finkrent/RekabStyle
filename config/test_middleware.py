from django.test import RequestFactory, SimpleTestCase, override_settings

from config.middleware import TrustedProxyClientIpMiddleware


class TrustedProxyClientIpMiddlewareTests(SimpleTestCase):
    @override_settings(TRUSTED_PROXY_IPS=("127.0.0.1/32",))
    def test_trusted_proxy_supplies_distinct_client_addresses(self):
        middleware = TrustedProxyClientIpMiddleware(lambda request: None)
        factory = RequestFactory()
        first = factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="198.51.100.10")
        second = factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="198.51.100.11")

        middleware.process_request(first)
        middleware.process_request(second)

        self.assertEqual(first.META["REMOTE_ADDR"], "198.51.100.10")
        self.assertEqual(second.META["REMOTE_ADDR"], "198.51.100.11")

    @override_settings(TRUSTED_PROXY_IPS=("127.0.0.1/32",))
    def test_untrusted_client_cannot_spoof_forwarded_address(self):
        middleware = TrustedProxyClientIpMiddleware(lambda request: None)
        request = RequestFactory().get(
            "/", REMOTE_ADDR="198.51.100.20", HTTP_X_REAL_IP="203.0.113.77"
        )

        middleware.process_request(request)

        self.assertEqual(request.META["REMOTE_ADDR"], "198.51.100.20")

    @override_settings(TRUSTED_PROXY_IPS=())
    def test_proxy_header_is_ignored_without_configured_trusted_proxies(self):
        middleware = TrustedProxyClientIpMiddleware(lambda request: None)
        request = RequestFactory().get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="198.51.100.10"
        )

        middleware.process_request(request)

        self.assertEqual(request.META["REMOTE_ADDR"], "127.0.0.1")
