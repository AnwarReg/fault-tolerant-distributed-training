"""Small Google API adapters using only Python's standard library."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def access_token():
    # The VM metadata server provides a short-lived token for its service account.
    request = Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/"
        "service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)["access_token"]


def cloud_request(url, method="GET", data=None, content_type="application/json"):
    headers = {"Authorization": f"Bearer {access_token()}"}
    if data is not None:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=20) as response:
        return response.read()


class GcsStore:
    def __init__(self, bucket, name="state/coordinator.json"):
        self.bucket = bucket
        self.name = name

    def load(self):
        # A missing object means the first round has not started yet.
        url = (f"https://storage.googleapis.com/storage/v1/b/{quote(self.bucket)}/o/"
               f"{quote(self.name, safe='')}?alt=media")
        try:
            return json.loads(cloud_request(url))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def save(self, state):
        # GCS replaces the whole JSON object atomically before the API replies.
        query = urlencode({"uploadType": "media", "name": self.name})
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{quote(self.bucket)}/o?{query}"
        cloud_request(url, method="POST", data=json.dumps(state).encode("utf-8"))


class LocalStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def save(self, state):
        # Replace a complete file so local restart tests never read half a write.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        os.replace(temporary, self.path)


class CertificateIssuer:
    def __init__(self, pool):
        self.pool = pool

    def sign(self, csr):
        # Only the coordinator service account can ask this CA pool to sign.
        url = f"https://privateca.googleapis.com/v1/{self.pool}/certificates"
        payload = json.dumps({"pemCsr": csr, "lifetime": "604800s"}).encode("utf-8")
        result = json.loads(cloud_request(url, method="POST", data=payload))
        return result["pemCertificate"], result.get("pemCertificateChain", [])
