import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request


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


def request_registry_token(registry, repository, username, password):
    params = urllib.parse.urlencode(
        {
            "service": "ghcr.io",
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

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)

    token = data.get("token") or data.get("access_token")

    if not isinstance(token, str) or not token:
        raise ValueError("Registry did not return an access token")

    return token


def check_manifest(registry, repository, tag, bearer_token):
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

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return classify_manifest_response(
                response.status,
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return classify_manifest_response(exc.code, body)


def main():
    parser = argparse.ArgumentParser(description="Check whether a Docker image tag exists")

    parser.add_argument("--registry", default="https://ghcr.io")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)

    args = parser.parse_args()

    username = os.environ.get("REGISTRY_USER")
    token = os.environ.get("REGISTRY_TOKEN")

    print(f"Registry: {args.registry}")
    print(f"Repository: {args.repository}")
    print(f"Tag: {args.tag}")

    if not username or not token:
        print("UNCERTAIN: Registry credentials are missing")
        return 2

    try:
        bearer_token = request_registry_token(
            args.registry,
            args.repository,
            username,
            token,
        )

        result = check_manifest(
            args.registry,
            args.repository,
            args.tag,
            bearer_token,
        )

    except (urllib.error.URLError, ValueError, OSError) as exc:
        print(f"UNCERTAIN: Registry request failed ({type(exc).__name__})")
        return 2

    if result == "EXISTS":
        print("EXISTS: Version tag already exists")
        return 1

    if result == "ABSENT":
        print("UNCERTAIN: Missing tag requires verified registry authorization")
        return 2

    print("UNCERTAIN: Registry response was inconclusive")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
