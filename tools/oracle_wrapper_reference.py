#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import read_jsonl
from cobol_guard.oracle.oracle_python_reference import run_reference_oracle


def main() -> None:
    parser = argparse.ArgumentParser(description="Reference wrapper for COBOL command mode contract")
    parser.add_argument("--input", required=True, help="Input transactions JSONL path")
    parser.add_argument("--output", required=True, help="Output oracle_result.json path")
    parser.add_argument("--business-date", required=True)
    args = parser.parse_args()

    txns = [Transaction.from_dict(item) for item in read_jsonl(Path(args.input))]
    result = run_reference_oracle(transactions=txns, business_date=args.business_date)
    payload = {
        "journal": [item.to_dict() for item in result.journal],
        "exceptions": [item.to_dict() for item in result.exceptions],
        "totals": result.totals.to_dict(),
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
