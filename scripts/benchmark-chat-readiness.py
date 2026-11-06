#!/usr/bin/env python3
"""Compare the real shell readiness loop against an isolated delayed HTTP API.

No MLX processes, LaunchAgents, configuration files or model weights are used.
The fixture starts its readiness timer at the first request, excluding shell
startup from the detection-lag measurement.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    return name + "() {" + source.split("\n" + name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def measure(source, delay):
    class API(BaseHTTPRequestHandler):
        def do_GET(self):
            now = time.monotonic()
            if self.server.first_request is None:
                self.server.first_request = now
            self.server.requests += 1
            ready = now >= self.server.first_request + delay
            self.send_response(200 if ready else 503)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), API)
    server.first_request = None
    server.requests = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = function(source, 'api_ready') + function(source, 'wait_for_api')
        script += f'\nPORT={server.server_port}\nwait_for_api 5\n'
        subprocess.run(['/bin/bash', '-c', script], check=True,
                       capture_output=True, text=True, timeout=15)
        finished = time.monotonic()
        return {
            'fixture_ready_ms': round(delay * 1000, 2),
            'shell_return_ms': round((finished - server.first_request) * 1000, 2),
            'detection_lag_ms': round((finished - server.first_request - delay) * 1000, 2),
            'requests': server.requests,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    baseline = subprocess.run(
        ['git', 'show', f'{args.baseline_ref}:scripts/mlx'], cwd=ROOT,
        check=True, capture_output=True, text=True).stdout
    current = (ROOT / 'scripts/mlx').read_text()
    report = {'fixture': 'delayed local HTTP API; no models', 'runs': {}}
    for label, source in [('baseline', baseline), ('patched', current)]:
        samples = [measure(source, delay) for _ in range(args.repeats)
                   for delay in (.15, .35, .55, .75, .95)]
        report['runs'][label] = {
            'samples': samples,
            'median_detection_lag_ms': statistics.median(row['detection_lag_ms'] for row in samples),
            'mean_detection_lag_ms': statistics.mean(row['detection_lag_ms'] for row in samples),
        }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
