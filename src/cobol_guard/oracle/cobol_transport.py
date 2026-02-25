from __future__ import annotations

import subprocess
from pathlib import Path

from cobol_guard.contracts import Transaction

TXN_RECORD_LENGTH = 88


def _encode_signed_int(value: int, width: int) -> str:
    sign = "+" if value >= 0 else "-"
    digits = str(abs(int(value))).zfill(width - 1)
    if len(digits) > width - 1:
        raise ValueError(f"Integer width overflow: value={value} width={width}")
    return f"{sign}{digits}"


def _decode_signed_int(raw: str) -> int:
    sign = -1 if raw.startswith("-") else 1
    return sign * int(raw[1:])


def transaction_to_fixed_width(txn: Transaction) -> str:
    fields = [
        txn.request_id.ljust(16)[:16],
        txn.operation.upper().ljust(8)[:8],
        txn.original_request_id.ljust(16)[:16],
        txn.account_id.ljust(12)[:12],
        _encode_signed_int(txn.amount_cents, 14),
        txn.business_date.ljust(8)[:8],
        txn.event_time.ljust(14)[:14],
    ]
    line = "".join(fields)
    if len(line) != TXN_RECORD_LENGTH:
        raise ValueError(f"Unexpected fixed-width transaction length: {len(line)}")
    return line


def fixed_width_to_transaction(line: str) -> Transaction:
    if len(line) < TXN_RECORD_LENGTH:
        raise ValueError(f"Transaction line too short: {len(line)} < {TXN_RECORD_LENGTH}")
    return Transaction(
        request_id=line[0:16].rstrip(),
        operation=line[16:24].strip().upper(),
        original_request_id=line[24:40].rstrip(),
        account_id=line[40:52].rstrip(),
        amount_cents=_decode_signed_int(line[52:66]),
        business_date=line[66:74].rstrip(),
        event_time=line[74:88].rstrip(),
    )


def write_transactions_dat(path: Path, transactions: list[Transaction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for txn in transactions:
            handle.write(transaction_to_fixed_width(txn))
            handle.write("\n")


def read_transactions_dat(path: Path) -> list[Transaction]:
    transactions: list[Transaction] = []
    if not path.exists():
        return transactions
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if not line:
                continue
            transactions.append(fixed_width_to_transaction(line=line))
    return transactions


def compile_cobol(source: Path, output_executable: Path) -> None:
    output_executable.parent.mkdir(parents=True, exist_ok=True)
    command = ["cobc", "-x", "-o", str(output_executable), str(source)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"cobc compile failed (exit={completed.returncode})\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )


def run_cobol_executable(executable: Path, working_dir: Path) -> None:
    completed = subprocess.run([str(executable)], cwd=str(working_dir), capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"cobol executable failed (exit={completed.returncode})\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
