# COBOL Guard

COBOL Guard is a modernization assurance project that proves behavioral parity between:
- `v1` COBOL oracle behavior
- `v2` Python implementation

The repository enforces deterministic execution, schema-governed canonicalization, signed evidence, and release gates.

Note: on Windows PowerShell, `gm` may resolve to `Get-Member`. Use `python -m cobol_guard.harness.cli ...` commands.

## Quick Start

1. Install in editable mode:
```bash
python -m pip install -e .[dev]
```

2. Run the oracle and candidate against the sample case:
```bash
python -m cobol_guard.harness.cli run --target oracle --case fixtures/cases/basic.yml
python -m cobol_guard.harness.cli run --target v2 --case fixtures/cases/basic.yml
```

3. Diff two run directories:
```bash
python -m cobol_guard.harness.cli diff --baseline-dir runs/<oracle-run> --candidate-dir runs/<v2-run>
```

4. Verify gates:
```bash
python -m cobol_guard.harness.cli verify --baseline-dir runs/<oracle-run> --candidate-dir runs/<v2-run>
```

5. Run adversarial parity case (out-of-order + duplicates + malformed ops):
```bash
python -m cobol_guard.harness.cli run --target oracle --case fixtures/cases/adversarial.yml
python -m cobol_guard.harness.cli run --target v2 --case fixtures/cases/adversarial.yml
python -m cobol_guard.harness.cli diff --baseline-dir runs/<oracle-adversarial-run> --candidate-dir runs/<v2-adversarial-run>
python -m cobol_guard.harness.cli verify --baseline-dir runs/<oracle-adversarial-run> --candidate-dir runs/<v2-adversarial-run>
```

6. Run restart adversarial case with failure injection, resume, and parity verify:
```bash
python -m cobol_guard.harness.cli run --target v2 --case fixtures/cases/adversarial_restart.yml --run-id demo-restart --fail-after-chunks 2
python -m cobol_guard.harness.cli run --target v2 --case fixtures/cases/adversarial_restart.yml --run-id demo-restart --resume
python -m cobol_guard.harness.cli run --target oracle --case fixtures/cases/adversarial_restart.yml
python -m cobol_guard.harness.cli verify --baseline-dir runs/<oracle-restart-run> --candidate-dir runs/demo-restart
```

7. Run benchmark report:
```bash
python -m cobol_guard.harness.cli benchmark --case fixtures/cases/basic.yml --profile benchmark/profile.yml
```

8. Start the candidate API:
```bash
v2-api
```

## Oracle Modes

- `python-reference` (default): in-process oracle implementation for local development.
- `cobol-command`: execute an external command that produces `oracle_result.json`.
- `cobol-executable`: compile/run `programs/v1/LEDGER01.cbl` with `cobc` and consume COBOL-produced fixed-width oracle artifacts directly.

Set external oracle mode:
```bash
set COBOL_GUARD_ORACLE_MODE=cobol-command
set COBOL_GUARD_ORACLE_COMMAND=python tools\\oracle_wrapper_reference.py --input "{input_jsonl}" --output "{output_json}" --business-date "{business_date}"
```

Set direct COBOL executable mode:
```bash
set COBOL_GUARD_ORACLE_MODE=cobol-executable
set COBOL_GUARD_COBOL_SOURCE=programs\\v1\\LEDGER01.cbl
set COBOL_GUARD_COBOL_BUILD_DIR=build\\cobol
python -m cobol_guard.harness.cli run --target oracle --case fixtures/cases/basic.yml
```

`oracle_result.json` contract:
```json
{
  "journal": [ { "...": "JournalRecord fields" } ],
  "exceptions": [ { "...": "ExceptionRecord fields" } ],
  "totals": { "...": "ReconcileTotals fields" }
}
```

## Governance Controls

- `SPEC.md` is the normative source for domain contract, canonicalization, invariants, and re-bless process.
- `governance/gate_policy.yml` contains deterministic severity mapping and threshold gates.
- Ed25519 signatures are required for baseline promotion.

Generate signer keys:
```bash
python -m cobol_guard.harness.cli keygen --name approver_a
python -m cobol_guard.harness.cli keygen --name approver_b
```

Sign a manifest:
```bash
python -m cobol_guard.harness.cli sign-manifest --manifest baselines/candidate/basic/baseline_manifest.json --key governance/keys/approver_a.private.pem
```

Promote candidate baseline to locked:
```bash
python -m cobol_guard.harness.cli promote-baseline \
  --manifest baselines/candidate/basic/baseline_manifest.json \
  --signature baselines/candidate/basic/baseline_manifest.approver_a.sig.json \
  --signature baselines/candidate/basic/baseline_manifest.approver_b.sig.json
```

## Repository Layout

- `SPEC.md`: system contract and control policy narrative.
- `schema-registry/`: schema authority and canonical byte encoding rules.
- `benchmark/profile.yml`: reproducible benchmark profile.
- `governance/`: keys and gate policy.
- `fixtures/`: deterministic sample inputs and case definitions.
- `src/cobol_guard/`: harness, candidate service, oracle adapter, governance logic.
- `.github/workflows/ci.yml`: test and gate automation.
- `.github/workflows/ci.yml` also contains scheduled/manual performance gate runs and a GnuCOBOL `cobol-executable` parity job (basic + adversarial cases).
- `tests/`: core behavioral and control tests.
