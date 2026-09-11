"""Standalone markdown renderer for billion_path_results.json.

Re-renders the markdown report from the saved JSON, so we don't have to
re-run the 25-minute simulation if the markdown writer needs fixes.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))

from billion_path_verification import (  # noqa: E402
    write_markdown,
    STRATEGIES,
    RESULTS_JSON,
    RESULTS_MD,
)


def main():
    with open(RESULTS_JSON) as f:
        out = json.load(f)

    # JSON-encoded pairs use string keys "A_vs_B"; convert back to tuple keys
    pairs_tuple = {}
    for k, v in out["pairs"].items():
        a, b = k.split("_vs_")
        pairs_tuple[(a, b)] = v

    out_md = dict(out)
    out_md["pairs"] = pairs_tuple

    write_markdown(out_md, RESULTS_MD)
    print(f"Wrote {RESULTS_MD}")


if __name__ == "__main__":
    main()
