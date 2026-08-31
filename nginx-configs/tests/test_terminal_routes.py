from pathlib import Path
from unittest import TestCase


CONFIG_PATH = Path(__file__).parents[1] / "dev_leo4_ru" / "internal_ssl.conf"


class TerminalRouteContractTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")

    def test_list_menu_file_is_owned_by_processing_backend(self):
        self.assertIn("location = /api/ListMenuFile", self.config)
        location = self.config.split("location = /api/ListMenuFile", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn(
            "proxy_pass http://processing-backend:8000/api/ListMenuFile", location
        )

    def test_client_cannot_spoof_certificate_identity_headers(self):
        self.assertIn("87.242.100.34 1;", self.config)
        self.assertIn(
            'map "$ssl_client_s_dn:$trusted_certificate_proxy"', self.config
        )
        self.assertNotIn('"" $http_x_client_cert', self.config)
        self.assertNotIn('"" $http_x_ssl_client_cert', self.config)
        self.assertIn('\n    ":1" $http_x_client_cert_dn;', self.config)