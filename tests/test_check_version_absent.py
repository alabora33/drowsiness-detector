import base64
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import check_version_absent
from scripts.check_version_absent import classify_manifest_response


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, "{}", "EXISTS"),
        (404, '{"errors":[{"code":"MANIFEST_UNKNOWN"}]}', "ABSENT"),
        (404, '{"errors":[{"code":"NAME_UNKNOWN"}]}', "ABSENT"),
        (401, "{}", "UNCERTAIN"),
        (403, "{}", "UNCERTAIN"),
        (500, "{}", "UNCERTAIN"),
        (404, "<html>Error</html>", "UNCERTAIN"),
        (404, '{"errors":[{"code":"DENIED"}]}', "UNCERTAIN"),
    ],
)
def test_classify_manifest_response(status, body, expected):
    assert classify_manifest_response(status, body) == expected


# --- End-to-end tests against a fake registry on 127.0.0.1 -----------------

USER = "release-bot"
SECRET = "ghs_super_secret_token_value"
BEARER = "registry_bearer_token_value"
REPO = "alabora33/drowsiness-detector"

TOKEN_OK = (200, f'{{"token": "{BEARER}"}}')
DENIED = (403, '{"errors":[{"code":"DENIED","message":"denied"}]}')
UNAUTHORIZED = (401, '{"errors":[{"code":"UNAUTHORIZED"}]}')
MANIFEST = (200, '{"schemaVersion": 2}')
MANIFEST_UNKNOWN = (404, '{"errors":[{"code":"MANIFEST_UNKNOWN"}]}')
NAME_UNKNOWN = (404, '{"errors":[{"code":"NAME_UNKNOWN"}]}')
SERVER_ERROR = (500, "oops")


class FakeRegistry:
    """Serves scripted responses; the last response of a route repeats."""

    def __init__(self, token=(TOKEN_OK,), manifest=(MANIFEST_UNKNOWN,)):
        self.routes = {"/token": list(token), "/v2/": list(manifest)}
        self.requests = []  # (path, headers)
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                registry.requests.append((self.path, dict(self.headers)))
                prefix = "/token" if self.path.startswith("/token") else "/v2/"
                queue = registry.routes[prefix]
                response = queue.pop(0) if len(queue) > 1 else queue[0]
                if callable(response):
                    return response(self)
                status, body = response
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def paths(self, prefix):
        return [path for path, _ in self.requests if path.startswith(prefix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def registry_factory():
    servers = []

    def make(**kwargs):
        server = FakeRegistry(**kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("REGISTRY_USER", USER)
    monkeypatch.setenv("REGISTRY_TOKEN", SECRET)


def run(registry_url, capsys, tag="0.1.0", repository=REPO):
    argv = ["--registry", registry_url, "--repository", repository, "--tag", tag]
    code = check_version_absent.main([*argv, "--retry-delay", "0"])
    output = capsys.readouterr().out
    # Credentials and the registry token must never appear in the logs.
    assert SECRET not in output
    assert BEARER not in output
    assert base64.b64encode(f"{USER}:{SECRET}".encode()).decode() not in output
    return code, output


def test_existing_tag_blocks_release(registry_factory, capsys):
    registry = registry_factory(manifest=[MANIFEST])
    code, output = run(registry.url, capsys)
    assert code == 1
    assert "EXISTS" in output


def test_missing_tag_allows_release(registry_factory, capsys):
    registry = registry_factory(manifest=[MANIFEST_UNKNOWN])
    code, output = run(registry.url, capsys)
    assert code == 0
    assert "tag not published yet" in output


def test_package_never_created_allows_first_release(registry_factory, capsys):
    registry = registry_factory(manifest=[NAME_UNKNOWN])
    code, output = run(registry.url, capsys)
    assert code == 0
    assert "first release" in output


def test_sends_push_scoped_basic_auth_then_bearer(registry_factory, capsys):
    registry = registry_factory(manifest=[MANIFEST_UNKNOWN])
    run(registry.url, capsys)
    (token_path, token_headers), (manifest_path, manifest_headers) = registry.requests
    assert "scope=repository%3Aalabora33%2Fdrowsiness-detector%3Apull%2Cpush" in token_path
    expected_basic = base64.b64encode(f"{USER}:{SECRET}".encode()).decode()
    assert token_headers["Authorization"] == f"Basic {expected_basic}"
    assert manifest_path == f"/v2/{REPO}/manifests/0.1.0"
    assert manifest_headers["Authorization"] == f"Bearer {BEARER}"
    assert "application/vnd.oci.image.index.v1+json" in manifest_headers["Accept"]


@pytest.mark.parametrize("token_response", [DENIED, UNAUTHORIZED])
def test_token_refused_is_uncertain_and_manifest_not_queried(
    registry_factory, capsys, token_response
):
    registry = registry_factory(token=[token_response])
    code, output = run(registry.url, capsys)
    assert code == 2
    assert "push authorization not proven" in output
    assert registry.paths("/v2/") == []


@pytest.mark.parametrize("manifest_response", [DENIED, UNAUTHORIZED])
def test_403_or_401_on_manifest_is_never_treated_as_absent(
    registry_factory, capsys, manifest_response
):
    registry = registry_factory(manifest=[manifest_response])
    code, output = run(registry.url, capsys)
    assert code == 2
    assert "UNCERTAIN" in output


def test_server_errors_are_retried_then_fail_closed(registry_factory, capsys):
    registry = registry_factory(manifest=[SERVER_ERROR])
    code, output = run(registry.url, capsys)
    assert code == 2
    assert "HTTP 500 after 3 attempts" in output
    assert len(registry.paths("/v2/")) == check_version_absent.MAX_ATTEMPTS


def test_transient_error_recovers_on_retry(registry_factory, capsys):
    registry = registry_factory(manifest=[(503, "busy"), MANIFEST_UNKNOWN])
    code, _ = run(registry.url, capsys)
    assert code == 0
    assert len(registry.paths("/v2/")) == 2


@pytest.mark.parametrize(
    "manifest_response",
    [
        (404, "<html>Not Found</html>"),
        (404, '{"errors":[{"code":"MANIFEST_UNKNOWN"},{"code":"DENIED"}]}'),
        (204, ""),
        (302, ""),
    ],
    ids=["html-404", "mixed-errors", "unexpected-204", "redirect"],
)
def test_unexpected_manifest_responses_are_uncertain(registry_factory, capsys, manifest_response):
    registry = registry_factory(manifest=[manifest_response])
    code, _ = run(registry.url, capsys)
    assert code == 2


@pytest.mark.parametrize(
    "token_response",
    [(200, "not json"), (200, '{"no_token": true}'), (200, '["list"]')],
    ids=["not-json", "no-token-field", "not-an-object"],
)
def test_bad_token_responses_are_uncertain(registry_factory, capsys, token_response):
    registry = registry_factory(token=[token_response])
    code, _ = run(registry.url, capsys)
    assert code == 2


def test_connection_refused_is_uncertain(registry_factory, capsys):
    registry = registry_factory()
    url = registry.url
    registry.close()  # nothing listens on that port any more
    code, output = run(url, capsys)
    assert code == 2
    assert "network error" in output


def test_timeout_is_bounded_and_uncertain(registry_factory, capsys, monkeypatch):
    monkeypatch.setattr(check_version_absent, "TIMEOUT_SECONDS", 0.2)

    def slow(handler):
        time.sleep(0.6)

    registry = registry_factory(manifest=[slow])
    started = time.monotonic()
    code, output = run(registry.url, capsys)
    assert code == 2
    assert "network error" in output
    assert time.monotonic() - started < 5


def test_truncated_response_is_uncertain(registry_factory, capsys):
    def truncated(handler):
        handler.send_response(404)
        handler.send_header("Content-Length", "500")
        handler.end_headers()
        handler.wfile.write(b'{"errors":')
        handler.close_connection = True

    registry = registry_factory(manifest=[truncated])
    code, _ = run(registry.url, capsys)
    assert code == 2


def test_redirect_does_not_leak_credentials(registry_factory, capsys):
    attacker = registry_factory()

    def redirect(handler):
        handler.send_response(302)
        handler.send_header("Location", f"{attacker.url}/token?stolen=1")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    registry = registry_factory(token=[redirect])
    code, _ = run(registry.url, capsys)
    assert code == 2
    assert attacker.requests == []


def test_missing_credentials_fail_without_network(registry_factory, capsys, monkeypatch):
    monkeypatch.delenv("REGISTRY_TOKEN")
    registry = registry_factory()
    code, output = run(registry.url, capsys)
    assert code == 2
    assert "credentials are missing" in output
    assert registry.requests == []


@pytest.mark.parametrize(
    ("registry_url", "repository", "tag"),
    [
        ("http://ghcr.io", REPO, "0.1.0"),  # credentials would travel in clear text
        ("https://ghcr.io", "Alabora33/Drowsiness-Detector", "0.1.0"),
        ("https://ghcr.io", REPO, "../../etc"),
        ("https://ghcr.io", REPO, ""),
    ],
    ids=["plain-http", "upper-case-repo", "path-in-tag", "empty-tag"],
)
def test_invalid_arguments_are_rejected_before_any_request(capsys, registry_url, repository, tag):
    code, output = run(registry_url, capsys, tag=tag, repository=repository)
    assert code == 2
    assert "UNCERTAIN" in output
