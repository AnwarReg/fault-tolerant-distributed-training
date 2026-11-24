"""Enroll a dummy worker and submit a deterministic placeholder update."""

import argparse
import json
import ssl
import subprocess
import time
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url, context, path, payload=None):
    # The server certificate is checked against the provided CA/certificate file.
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    request = Request(url + path, data=body, headers=headers)
    for attempt in range(8):
        try:
            with urlopen(request, context=context, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (502, 503, 504) or attempt == 7:
                raise
        except (URLError, TimeoutError):
            if attempt == 7:
                raise
        # A VM restart or brief load balancer outage should not abort training.
        time.sleep(min(2 ** attempt, 10))


def enroll(args):
    # The private key stays on this worker; only its CSR crosses the network.
    key = Path(args.key)
    csr = key.with_suffix(".csr")
    if key.exists():
        raise SystemExit(f"Refusing to overwrite existing key: {key}")
    subprocess.run([
        "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={args.worker_id}",
        "-addext", "keyUsage=digitalSignature",
        "-addext", "extendedKeyUsage=clientAuth",
    ], check=True)
    if os.name != "nt":
        key.chmod(0o600)
    context = ssl.create_default_context(cafile=args.server_cert)
    result = request_json(args.url, context, "/enroll", {
        "token": args.token,
        "csr": csr.read_text(),
    })
    Path(args.cert).write_text(result["certificate"] + "".join(result["chain"]))
    csr.unlink()
    print(f"Enrolled {result['worker_id']}; certificate saved to {args.cert}")


def run(args):
    # mTLS proves possession of the worker key on every request.
    context = ssl.create_default_context(cafile=args.server_cert)
    context.load_cert_chain(args.cert, args.key)
    previous_round = 0
    for _ in range(args.rounds):
        # A worker can finish before the other workers; keep checking until a new round opens.
        while True:
            task = request_json(args.url, context, "/v1/task")
            if task["round_id"] > previous_round:
                break
            request_json(args.url, context, "/v1/heartbeat", {})
            time.sleep(3)
        print("Task:", task)
        remaining = args.work_seconds
        while remaining > 0:
            interval = min(remaining, 10)
            time.sleep(interval)
            remaining -= interval
            request_json(args.url, context, "/v1/heartbeat", {})
        result = request_json(args.url, context, "/v1/result", {
            "round_id": task["round_id"],
            "value": args.value,
            "weight": args.weight,
        })
        print("Result:", result)
        previous_round = task["round_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("enroll", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--url", required=True, help="https://LOAD_BALANCER_IP[:PORT]")
        command.add_argument("--server-cert", required=True)
        command.add_argument("--cert", required=True)
        command.add_argument("--key", required=True)
        if name == "enroll":
            command.add_argument("--worker-id", required=True)
            command.add_argument("--token", required=True)
        else:
            command.add_argument("--rounds", type=int, default=1)
            command.add_argument("--work-seconds", type=float, default=2)
            command.add_argument("--value", type=float, default=1.0)
            command.add_argument("--weight", type=int, default=1)
    args = parser.parse_args()
    enroll(args) if args.command == "enroll" else run(args)


if __name__ == "__main__":
    main()
