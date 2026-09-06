from pathlib import Path
from unittest import TestCase


DEV_LEO4_RU_DIR = Path(__file__).parents[1] / "dev_leo4_ru"


class DocsRouteContractTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port_3000_conf = (DEV_LEO4_RU_DIR / "port_3000.conf").read_text(encoding="utf-8")
        cls.port_80_conf = (DEV_LEO4_RU_DIR / "port_80.conf").read_text(encoding="utf-8")
        cls.default_conf = (DEV_LEO4_RU_DIR / "default.conf").read_text(encoding="utf-8")

    def test_port_3000_proxies_docs_and_openapi_without_jwt(self):
        docs_location_pattern = "location ~ ^/(docs|openapi.json|redoc|swagger|legacy-docs)"
        self.assertIn(docs_location_pattern, self.port_3000_conf)

        block = self.port_3000_conf.split(docs_location_pattern, 1)[1].split("}", 1)[0]
        self.assertIn("auth_jwt_enabled off;", block)
        self.assertIn("proxy_pass $app1_upstream;", block)
        self.assertIn("proxy_set_header Host $host;", block)

    def test_port_80_redirects_to_port_3000(self):
        self.assertIn("listen 80;", self.port_80_conf)
        self.assertIn("server_name dev.leo4.ru;", self.port_80_conf)
        self.assertIn("return 301 https://$host:3000$request_uri;", self.port_80_conf)

    def test_default_conf_proxies_docs_to_app1(self):
        docs_location_pattern = "location ~ ^/(docs|openapi.json|redoc|swagger|legacy-docs)"
        self.assertIn(docs_location_pattern, self.default_conf)

        block = self.default_conf.split(docs_location_pattern, 1)[1].split("}", 1)[0]
        self.assertIn("proxy_pass http://app1:8000;", block)
        self.assertIn("proxy_set_header Host $host;", block)
