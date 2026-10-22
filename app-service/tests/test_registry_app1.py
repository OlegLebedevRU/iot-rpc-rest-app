import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "registry_app1", Path(__file__).resolve().parents[2] / "deploy/registry_app1.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize(
    "proxy",
    ["http://fixture:invalid@localhost:1234", "http://external.invalid:1234"],
)
def test_build_proxy_rejects_credentials_and_external_endpoints(proxy):
    with pytest.raises(ValueError, match="unauthenticated loopback"):
        release.build_proxy_args(proxy)
