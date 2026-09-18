"""Run every pgTAP suite transactionally; suppress raw CLI/provider diagnostics.

Uses the already authenticated, linked Supabase CLI. No database reset, secrets,
real customer fixtures, dependency installs, or persistent test grants.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_suite(path: Path, command: list[str], migration: str = "") -> dict:
    sql = path.read_text(encoding="utf-8")
    if not re.match(r"\s*begin\s*;", sql, re.IGNORECASE) or not re.search(
        r"rollback\s*;\s*$", sql, re.IGNORECASE
    ):
        raise ValueError("Suite must be bounded by BEGIN/ROLLBACK")
    sql = re.sub(
        r"\bbegin\s*;",
        lambda _: (
            "begin;\n"
            + migration
            + "\ncreate extension if not exists pgtap with schema extensions;\nset local search_path = public, extensions;"
        ),
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    ending = """
reset role;
create temporary table security_test_summary as select * from finish();
do $security_check$
begin
    if exists(select 1 from security_test_summary where finish like '#%') then
        raise exception 'Security suite failed';
    end if;
end;
$security_check$;
select * from security_test_summary;
rollback;
"""
    sql, replaced = re.subn(
        r"select\s+\*\s+from\s+finish\(\);\s*rollback;\s*$",
        lambda _: ending,
        sql,
        flags=re.IGNORECASE,
    )
    if replaced != 1:
        raise ValueError("Unsupported suite ending")
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="security-suite-", dir=ROOT / ".tmp"
    ) as directory:
        wrapper = Path(directory) / "rollback.sql"
        wrapper.write_text(sql, encoding="utf-8")
        if Path(command[0]).stem == "psql":
            result = subprocess.run(
                command + ["-f", str(wrapper)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            count = len(re.findall(r"^(?:ok|not ok) \d+", result.stdout, re.MULTILINE))
            failed = result.returncode != 0 or bool(
                re.search(r"^not ok \d+", result.stdout, re.MULTILINE)
            )
            summary = {
                "suite": path.name,
                "assertions": count,
                "result": "UNVERIFIED" if not count else "FAIL" if failed else "PASS",
            }
            if failed:
                import os

                diagnostic = result.stderr
                for key, value in os.environ.items():
                    if key.startswith("PG") and value:
                        diagnostic = diagnostic.replace(value, "<redacted>")
                headline = re.search(r"ERROR:\s*([^\n\\]+)", diagnostic)
                summary["diagnostic"] = (
                    headline.group(1)[:240]
                    if headline
                    else "Connection/SQL failed; raw diagnostics suppressed"
                )
                summary["failed_assertions"] = re.findall(
                    r"^not ok \d+[^\n]*", result.stdout, re.MULTILINE
                )
            return summary
        result = subprocess.run(
            command
            + ["db", "query", "--linked", "--file", str(wrapper), "--output", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    if result.returncode:
        # Synthetic rollback tests only: report the SQL error headline, never
        # the surrounding provider request, SQL payload, or connection values.
        headline = re.search(r"ERROR:\s*([^\n\\]+)", result.stderr)
        return {
            "suite": path.name,
            "result": "FAIL",
            "reason": headline.group(1)[:240]
            if headline
            else "SQL/CLI failed; raw diagnostics suppressed",
        }
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    rows = payload.get("rows", [])
    plan = next(
        (
            str(value)
            for row in rows
            for value in row.values()
            if re.fullmatch(r"1\.\.\d+", str(value))
        ),
        None,
    )
    # Planned suites' finish() may return no rows on success; take their declared plan.
    declared = re.search(r"select\s+plan\((\d+)\)", sql, re.IGNORECASE)
    count = (
        int(plan.split("..")[1])
        if plan
        else int(declared.group(1))
        if declared
        else None
    )
    return {
        "suite": path.name,
        "assertions": count,
        "result": "PASS" if count else "UNVERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli", help="Existing Supabase executable, otherwise npx supabase"
    )
    parser.add_argument("--suite", help="Optional single suite filename")
    parser.add_argument(
        "--psql",
        action="store_true",
        help="Reuse an ephemeral CLI login with installed psql",
    )
    parser.add_argument(
        "--preflight-016",
        action="store_true",
        help="Apply only migration 016 inside each rolled-back test transaction",
    )
    args = parser.parse_args()
    migration = (
        (ROOT / "supabase/migrations/202609180016_security_hardening.sql").read_text(
            encoding="utf-8"
        )
        if args.preflight_016
        else ""
    )
    command = [args.cli] if args.cli else [shutil.which("npx") or "npx", "supabase"]
    if args.psql:
        import os

        from rate_limit_concurrency import connection_environment

        environment = connection_environment()
        environment["PGOPTIONS"] = (
            environment.get("PGOPTIONS", "") + " -c role=postgres"
        )
        os.environ.update(
            {key: value for key, value in environment.items() if key.startswith("PG")}
        )
        command = [
            shutil.which("psql") or "psql",
            "-X",
            "-q",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
        ]
    suites = sorted((ROOT / "supabase/tests/database").glob("*.test.sql"))
    if args.suite:
        suites = [path for path in suites if path.name == args.suite]
        if not suites:
            parser.error("Unknown suite")
    results = []
    for suite in suites:
        try:
            result = run_suite(suite, command, migration)
        except (ValueError, subprocess.TimeoutExpired):
            result = {
                "suite": suite.name,
                "result": "UNVERIFIED",
                "reason": "Test runner or CLI timed out/invalid summary",
            }
        results.append(result)
        print(json.dumps(result), flush=True)
    return 0 if all(result["result"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
