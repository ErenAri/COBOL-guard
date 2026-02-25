import json
import sys
from pathlib import Path

from cobol_guard.contracts import Transaction
from cobol_guard.io_utils import read_jsonl
from cobol_guard.oracle.adapter import OracleAdapter


def test_oracle_adapter_command_mode(monkeypatch, tmp_path: Path) -> None:
    script_path = tmp_path / "oracle_wrapper.py"
    script_path.write_text(
        "\n".join(
            [
                "import argparse, json",
                "from pathlib import Path",
                "ap = argparse.ArgumentParser()",
                "ap.add_argument('--input', required=True)",
                "ap.add_argument('--output', required=True)",
                "ap.add_argument('--business-date', required=True)",
                "args = ap.parse_args()",
                "txns = []",
                "for raw in Path(args.input).read_text(encoding='utf-8').splitlines():",
                "    if raw.strip():",
                "        txns.append(json.loads(raw))",
                "balances = {}",
                "journal = []",
                "exceptions = []",
                "total_post = 0",
                "for index, txn in enumerate(txns, start=1):",
                "    acct = txn['account_id']",
                "    before = balances.get(acct, 0)",
                "    effect = int(txn.get('amount_cents', 0)) if txn['operation'] == 'POST' else 0",
                "    after = before + effect",
                "    balances[acct] = after",
                "    if txn['operation'] == 'POST':",
                "        total_post += effect",
                "    journal.append({",
                "        'sequence_no': index,",
                "        'business_date': args.business_date,",
                "        'account_id': acct,",
                "        'request_id': txn['request_id'],",
                "        'operation': txn['operation'],",
                "        'original_request_id': txn.get('original_request_id', ''),",
                "        'amount_cents': effect,",
                "        'balance_before_cents': before,",
                "        'balance_after_cents': after,",
                "        'status': 'APPLIED',",
                "        'audit_event': 'WRAPPER_APPLIED'",
                "    })",
                "totals = {",
                "    'business_date': args.business_date,",
                "    'total_post_cents': total_post,",
                "    'total_reverse_cents': 0,",
                "    'net_delta_cents': total_post,",
                "    'closing_total_cents': sum(balances.values()),",
                "    'records_processed': len(journal),",
                "    'applied_records': len(journal),",
                "    'exception_count': 0",
                "}",
                "payload = {'journal': journal, 'exceptions': exceptions, 'totals': totals}",
                "Path(args.output).write_text(json.dumps(payload), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )

    template = f"\"{sys.executable}\" \"{script_path}\" --input \"{{input_jsonl}}\" --output \"{{output_json}}\" --business-date \"{{business_date}}\""
    monkeypatch.setenv("COBOL_GUARD_ORACLE_MODE", "cobol-command")
    monkeypatch.setenv("COBOL_GUARD_ORACLE_COMMAND", template)
    adapter = OracleAdapter.from_environment()
    fixture = read_jsonl(Path("fixtures/inputs/basic_transactions.jsonl"))[:2]
    transactions = [Transaction.from_dict(item) for item in fixture]

    result = adapter.run(transactions=transactions, business_date="20260110")
    assert len(result.journal) == 2
    assert result.totals.total_post_cents == 20000
