"""Real PostgreSQL final-slot race, coordinated by row locks, not AI/Python mocks.

Requires existing psql and authenticated Supabase CLI, or PG* connection env.
CLI dump --dry-run is captured privately to reuse an ephemeral CLI login; no
password is printed, persisted, or placed in process arguments. Only random
synthetic infrastructure counters are committed, then removed in finally.
"""

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from postgres_connection import Postgres, SqlFailure

ROOT = Path(__file__).resolve().parents[2]


def connection_environment() -> dict[str, str]:
    environment = os.environ.copy()
    if not all(environment.get(key) for key in ("PGHOST", "PGUSER", "PGPASSWORD")):
        result = subprocess.run(
            [
                shutil.which("npx") or "npx",
                "supabase",
                "db",
                "dump",
                "--linked",
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Ephemeral CLI database connection unavailable")
        for line in result.stdout.splitlines():
            if line.strip().startswith("export PG"):
                for assignment in shlex.split(line.strip())[1:]:
                    key, separator, value = assignment.partition("=")
                    if separator and key.startswith("PG"):
                        environment[key] = value
    if not all(environment.get(key) for key in ("PGHOST", "PGUSER", "PGPASSWORD")):
        raise RuntimeError("No safe database connection available")
    environment["PGCONNECT_TIMEOUT"] = "10"
    return environment


def race(environment: dict[str, str], scope: str, maximum: int) -> dict:
    subject = str(uuid4())
    prefix = "supportpilot_security_" + uuid4().hex
    coordinator = Postgres(environment)
    workers = []
    threads = []
    outcomes = []
    cleanup_verified = False
    try:
        for index in range(2):
            workers.append(Postgres(environment, f"{prefix}_{index}"))
        worker_pids = [
            int(connection.query("select pg_backend_pid();")[0][0])
            for connection in workers
        ]
        if len(set(worker_pids)) != 2:
            raise RuntimeError(
                "The two clients did not obtain independent database sessions"
            )
        coordinator.query(
            f"insert into public.customer_api_rate_limits values ('{scope}','{subject}', to_timestamp(floor(extract(epoch from clock_timestamp())/60)*60),{maximum - 1},to_timestamp(floor(extract(epoch from clock_timestamp())/60)*60)+interval '1 minute');"
        )
        coordinator.query(
            f"begin; select * from public.customer_api_rate_limits where scope='{scope}' and subject_id='{subject}' for update;"
        )
        start = threading.Barrier(3)

        def claim(connection):
            try:
                start.wait(timeout=5)
                connection.query(
                    f"begin; select app_private.consume_customer_rate_limit('{scope}','{subject}'); commit;"
                )
                outcomes.append("CLAIMED")
            except SqlFailure as error:
                outcomes.append(error.code)
                connection.query("rollback;")
            except threading.BrokenBarrierError:
                outcomes.append("COORDINATION_FAILED")

        threads = [
            threading.Thread(target=claim, args=(connection,), daemon=True)
            for connection in workers
        ]
        for thread in threads:
            thread.start()
        start.wait(timeout=5)
        waiting = False
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            # Observe actual ungranted locks by backend PID. Poolers need not
            # propagate application_name, and activity snapshots may be cached.
            rows = coordinator.query(
                f"select count(distinct pid) from pg_locks where pid in ({worker_pids[0]},{worker_pids[1]}) and not granted;"
            )
            if rows == [["2"]]:
                waiting = True
                break
        if not waiting:
            raise RuntimeError(
                "Both real transactions did not reach the lock barrier; observed waiters="
                + rows[0][0]
                + "; outcomes="
                + ",".join(sorted(outcomes))
            )
        coordinator.query("commit;")
        for thread in threads:
            thread.join(timeout=17)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("A real claim exceeded its statement timeout")
        counters = coordinator.query(
            f"select request_count from public.customer_api_rate_limits where scope='{scope}' and subject_id='{subject}' and window_started_at=to_timestamp(floor(extract(epoch from clock_timestamp())/60)*60);"
        )
        passed = sorted(outcomes) == ["CLAIMED", "PT429"] and counters == [
            [str(maximum)]
        ]
        result = {
            "scope": scope,
            "result": "PASS" if passed else "FAIL",
            "independent_connections": 2,
            "both_waited_at_lock_barrier": waiting,
            "outcomes": sorted(outcomes),
            "final_count": counters[0][0] if counters else None,
        }
    finally:
        coordinator.query("rollback;")
        for thread in threads:
            thread.join(timeout=17)
        for index, connection in enumerate(workers):
            # Never concurrently PQfinish a connection whose query is hung.
            if index >= len(threads) or not threads[index].is_alive():
                connection.close()
        try:
            coordinator.query(
                f"delete from public.customer_api_rate_limits where subject_id='{subject}' and scope='{scope}';"
            )
            cleanup_verified = coordinator.query(
                f"select count(*) from public.customer_api_rate_limits where subject_id='{subject}';"
            ) == [["0"]]
        finally:
            coordinator.close()
    result["synthetic_counter_removed"] = cleanup_verified
    if not cleanup_verified:
        result["result"] = "FAIL"
    return result


def main() -> int:
    try:
        environment = connection_environment()
        results = [
            race(environment, scope, maximum)
            for scope, maximum in [("session_minute", 30), ("turn_minute", 6)]
        ]
        for result in results:
            print(json.dumps(result), flush=True)
        return 0 if all(result["result"] == "PASS" for result in results) else 1
    except (
        RuntimeError,
        subprocess.SubprocessError,
        OSError,
        ValueError,
        threading.BrokenBarrierError,
    ) as error:
        print(
            json.dumps(
                {
                    "result": "UNVERIFIED",
                    "reason": str(error)
                    if type(error) in (RuntimeError, SqlFailure)
                    else "Connection/coordination failed; raw diagnostics suppressed",
                }
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
