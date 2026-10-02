#!/usr/bin/env python3
"""Compare artifacts produced by the real Swift and Kotlin CI jobs."""
import json
from pathlib import Path
import sys
from replay import canonical, compare

if __name__=='__main__':
    left,right=[json.loads(Path(p).read_text()) for p in sys.argv[1:3]]
    if not left or not right:raise SystemExit('Empty parity evidence')
    compare(canonical(left),canonical(right))
    print(f'Native semantic/state parity passed for {len(left)} scenarios (numeric tolerance 1e-9).')
