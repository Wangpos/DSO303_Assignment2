#!/usr/bin/env python3
"""Small exam-peak load generator (stdlib only).

Health mode (no auth):
    python3 scripts/load_test.py --url https://dxxxx.cloudfront.net --workers 20 --requests 25

Autosave mode (sign in as student1 in the browser, start the demo exam, then copy
the id_token from DevTools > Application > Session Storage and the attempt id
from the network tab):
    ID_TOKEN=eyJ... python3 scripts/load_test.py --url https://dxxxx.cloudfront.net \
        --attempt <attempt-id> --question <question-id> --workers 20 --requests 25

NOTE: a new AWS account has a Lambda concurrency quota of 10, so large runs will
show throttling (HTTP 429/503). That is the reason the README asks for a quota
increase before exam week.
"""
import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


def one_request(args, token):
    if args.attempt:
        url = f"{args.url}/api/attempts/{args.attempt}/answers"
        body = json.dumps({"answers": [{"question_id": args.question, "response": "1"}]}).encode()
        req = urllib.request.Request(url, data=body, method="PUT", headers={
            "Authorization": f"Bearer {token}", "content-type": "application/json"})
    else:
        req = urllib.request.Request(f"{args.url}/api/health?deep=1")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            code = res.status
    except urllib.error.HTTPError as err:
        code = err.code
    except Exception:  # noqa: BLE001
        code = 0
    return code, (time.perf_counter() - start) * 1000


def worker(args, token):
    return [one_request(args, token) for _ in range(args.requests)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--requests", type=int, default=25)
    p.add_argument("--attempt")
    p.add_argument("--question")
    args = p.parse_args()
    args.url = args.url.rstrip("/")
    token = os.environ.get("ID_TOKEN", "")
    if args.attempt and not (token and args.question):
        p.error("autosave mode needs ID_TOKEN and --question")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = [r for batch in pool.map(lambda _: worker(args, token), range(args.workers)) for r in batch]
    elapsed = time.time() - t0

    codes = Counter(c for c, _ in results)
    lat = sorted(ms for _, ms in results)
    print(f"requests: {len(results)} in {elapsed:.1f}s  ({len(results) / elapsed:.1f} req/s)")
    print(f"status codes: {dict(codes)}")
    print(f"latency ms: p50={statistics.median(lat):.0f}  p95={lat[int(len(lat) * .95) - 1]:.0f}  max={lat[-1]:.0f}")


if __name__ == "__main__":
    main()
