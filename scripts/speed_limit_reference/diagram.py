#!/usr/bin/env python3
"""Render developer diagram source from the runtime artifact; never edit policy."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--format", choices=["dot", "mermaid"], default="dot")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
policy = json.loads((root / "shared/speed-limit-reference/policy-v1.1.0.json").read_text())

if args.format == "dot":
    def quote(text):
        return json.dumps(text)
    print('digraph reference { rankdir=LR; node [shape=box, fontname="Helvetica"];')
    print('label="Speed-limit reference ' + policy["version"] + ' — first matching transition, then source projection";')
    print('input [label="Validated normalized event\\nAdvance clock/distance and expire claims"];')
    print('select [shape=diamond, label="SELECT\\nfirst present register"];')
    for index, row in enumerate(policy["transitions"]):
        label = f'{row["id"]}: {row["on"]}\n{row["guard"]}\n' + ', '.join(row["actions"])
        print(f'{row["id"]} [label={quote(label)}];')
        previous = "input" if index == 0 else policy["transitions"][index-1]["id"]
        print(f'{previous} -> {row["id"]} [label="' + ("" if index == 0 else "no match") + '"];')
        print(f'{row["id"]} -> select [label="match / actions"];')
    for row in policy["selection"]:
        label = row["register"] or "no value"
        print(f'select -> {row["state"]} [label={quote(label)}];')
    print('LAST_KNOWN [label="LAST_KNOWN\\nstale display only / no penalty baseline"];')
    print('UNKNOWN [label="UNKNOWN\\nno value / no penalty baseline"];')
    print('}')
else:
    print('stateDiagram-v2')
    print('    [*] --> ' + policy["initial_state"] + ': new drive')
    print('    state SELECT <<choice>>')
    for state in policy["states"]:
        print(f'    {state} --> SELECT: normalized event / configured transition')
    for row in policy["selection"]:
        label = row["register"] or "no remembered value"
        print(f'    SELECT --> {row["state"]}: {label}')
    print('    note right of SELECT')
    print('        Priority: ' + ' > '.join(policy["priority"]))
    print(f'        Ordinary expiry: {policy["limits"]["ordinary_max_distance_m"]} m OR {policy["limits"]["ordinary_max_age_s"]} s')
    print('        Camera candidate/applicability pipeline is external')
    print('        LAST_KNOWN is display-only')
    print('    end note')
