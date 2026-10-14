"""Fail-closed check that a version tag is not yet published to a container registry.

Used by the release workflow before anything is built or pushed:

    REGISTRY_USER=... REGISTRY_TOKEN=... \
        python3 scripts/check_version_absent.py --repository owner/name --tag 1.2.3

Exit codes:
    0  ABSENT     the registry explicitly said the tag (or the whole package) does
                  not exist, after we proved we are authorized to push to it
    1  EXISTS     the tag already exists; versions are immutable
    2  UNCERTAIN  anything else (auth failure, network error, timeout, 5xx,
                  unexpected response); the release must stop

A token is requested with the same `pull,push` scope the publish step needs, so
a 404 afterwards cannot be an authorization problem in disguise. A 401/403 is
never treated as "absent".
"""

import argparse
import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# OCI distribution spec naming rules (repository lower-case, tag up to 128 chars).
REPOSITORY_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


class RegistryError(Exception):
    """The registry could not give a trustworthy answer."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib forwards the Authorization header to redirect targets, even on
    # another host. Never follow redirects; a 3xx is reported as UNCERTAIN.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def classify_manifest_response(status, body):
    if status == 200:
        return "EXISTS"

    if status == 404:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return "UNCERTAIN"

        if not isinstance(data, dict):
            return "UNCERTAIN"

        errors = data.get("errors", [])

        if not isinstance(errors, list):
            return "UNCERTAIN"

        allowed_codes = {"MANIFEST_UNKNOWN", "NAME_UNKNOWN"}

        if (
            len(errors) == 1
            and isinstance(errors[0], dict)
            and errors[0].get("code") in allowed_codes
        ):
            return "ABSENT"

        return "UNCERTAIN"

    return "UNCERTAIN"


def registry_error_codes(body):
    """Registry error codes from a response body, for log messages (never secrets)."""
    try:
        errors = json.loads(body).get("errors", [])
        return ",".join(str(e.get("code")) for e in errors if isinstance(e, dict)) or "-"
    except (json.JSONDecodeError, TypeError, AttributeError):
        return "-"


def _send(request, retry_delay):
    """Return (status, body) for any HTTP response, retrying transient failures.

    Raises RegistryError when no usable HTTP response was received.
    """
    problem = "no attempt made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
                status, body = response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            # Connection refused, DNS failure, timeout, truncated response, ...
            problem = f"network error ({type(exc).__name__})"
            status = None
        if status is not None:
            if status not in RETRYABLE_STATUSES:
                return status, body
            problem = f"HTTP {status}"
        if attempt < MAX_ATTEMPTS:
            time.sleep(retry_delay * attempt)
    raise RegistryError(f"{problem} after {MAX_ATTEMPTS} attempts")


def request_registry_token(registry, repository, username, password, retry_delay=1.0):
    params = urllib.parse.urlencode(
        {
            "service": urllib.parse.urlparse(registry).hostname,
            "scope": f"repository:{repository}:pull,push",
        }
    )

    url = f"{registry.rstrip('/')}/token?{params}"

    credentials = f"{username}:{password}".encode()
    basic_auth = base64.b64encode(credentials).decode("ascii")

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Accept": "application/json",
        },
    )

    status, body = _send(request, retry_delay)
    if status != 200:
        raise RegistryError(
            f"token request returned HTTP {status} ({registry_error_codes(body)}); "
            "push authorization not proven, so absence cannot be verified"
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise RegistryError("token response is not JSON") from None

    token = (data.get("token") or data.get("access_token")) if isinstance(data, dict) else None

    if not isinstance(token, str) or not token:
        raise RegistryError("Registry did not return an access token")

    return token


def check_manifest(registry, repository, tag, bearer_token, retry_delay=1.0):
    """Return (result, detail) where result is EXISTS, ABSENT or UNCERTAIN."""
    url = f"{registry.rstrip('/')}/v2/{repository}/manifests/{tag}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Accept": ", ".join(
                [
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                ]
            ),
        },
        method="GET",
    )

    status, body = _send(request, retry_delay)
    detail = f"HTTP {status}, registry code {registry_error_codes(body)}"
    return classify_manifest_response(status, body), detail


def validate_arguments(registry, repository, tag):
    parsed = urllib.parse.urlparse(registry)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS
    ):
        raise ValueError("registry must use https (plain http only for localhost tests)")
    if not REPOSITORY_RE.match(repository):
        raise ValueError(f"invalid repository name {repository!r} (must be lower-case)")
    if not TAG_RE.match(tag):
        raise ValueError(f"invalid tag {tag!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check whether a Docker image tag exists")

    parser.add_argument("--registry", default="https://ghcr.io")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="seconds before the first retry (grows linearly); tests use 0",
    )

    args = parser.parse_args(argv)

    username = os.environ.get("REGISTRY_USER")
    token = os.environ.get("REGISTRY_TOKEN")

    print(f"Registry: {args.registry}")
    print(f"Repository: {args.repository}")
    print(f"Tag: {args.tag}")

    try:
        validate_arguments(args.registry, args.repository, args.tag)
    except ValueError as exc:
        print(f"UNCERTAIN: {exc}")
        return 2

    if not username or not token:
        print("UNCERTAIN: Registry credentials are missing")
        return 2

    try:
        bearer_token = request_registry_token(
            args.registry,
            args.repository,
            username,
            token,
            args.retry_delay,
        )

        result, detail = check_manifest(
            args.registry,
            args.repository,
            args.tag,
            bearer_token,
            args.retry_delay,
        )

    except RegistryError as exc:
        print(f"UNCERTAIN: Registry request failed: {exc}")
        return 2
    except Exception as exc:  # fail closed on anything unexpected, without a traceback
        print(f"UNCERTAIN: Unexpected error ({type(exc).__name__})")
        return 2

    if result == "EXISTS":
        print(f"EXISTS: Version tag already exists ({detail}); versions are immutable")
        return 1

    if result == "ABSENT":
        if "NAME_UNKNOWN" in detail:
            reason = "package not created yet (first release)"
        else:
            reason = "tag not published yet"
        print(f"ABSENT: {reason} ({detail}); push authorization verified")
        return 0

    print(f"UNCERTAIN: Registry response was inconclusive ({detail})")
    return 2


if __name__ == "__main__":
    sys.exit(main())
