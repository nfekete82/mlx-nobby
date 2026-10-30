#!/usr/bin/env python3
"""Read-only macOS telemetry for ONE existing job; never submits or retries GPU work."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_coordinator

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('job_id')
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--seconds',type=int,default=1800)
args=parser.parse_args()
if not re.fullmatch('[a-f0-9]{24}',args.job_id) or not 1<=args.seconds<=7200:
    parser.error('Expected a local job ID and a deadline between 1 and 7200 seconds')
source=Path.home()/'.config/mlx-web/video-jobs'/f'{args.job_id}.json'
deadline=time.monotonic()+args.seconds
args.out.parent.mkdir(parents=True,exist_ok=True)
with args.out.open('x') as output:
    while time.monotonic()<deadline:
        job=json.loads(source.read_text())
        row={'timestamp':time.time(),'status':job['status'],'phase':job.get('phase'),
             'stage':job.get('stage_number'),'memory':runtime_coordinator.memory_budget_snapshot()}
        output.write(json.dumps(row)+'\n');output.flush()
        if job['status'] in {'completed','failed','cancelled'}:
            print(json.dumps({'status':job['status'],'error':job.get('error')}))
            break
        time.sleep(2)
    else:
        raise SystemExit('Telemetry deadline reached; job was not changed or retried')
