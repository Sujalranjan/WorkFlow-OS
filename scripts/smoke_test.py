"""End-to-end smoke test against a running WorkFlowOS stack (used by CI; safe to run by hand).

    python scripts/smoke_test.py --api http://localhost:8000 --email you@example.com --password ...

Signs in, loads the sample browser routine, turns it into an approved workflow, queues a DRY RUN
and waits for the worker to finish it, then queues verification. A dry run changes nothing
outside WorkFlowOS, so this is safe against any install; it does add the sample activity and a
"Customer Replacement Request" workflow, so prefer a test install.

Standard library only, so it runs on a bare CI runner.
"""

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body=None, expect=(200, 201, 202)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-WorkflowOS-CSRF": "1"},
        )
        try:
            with self.opener.open(req, timeout=60) as res:
                status, payload = res.status, res.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        if status not in expect:
            raise SystemExit(f"{method} {path} -> HTTP {status}: {payload[:500].decode(errors='replace')}")
        return json.loads(payload) if payload else None


def wait_for_job(api: Api, job: dict, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while job["status"] in ("queued", "running"):
        if time.time() > deadline:
            raise SystemExit(f"Job {job['job_id']} ({job['kind']}) still {job['status']} after {timeout}s: is the worker running?")
        time.sleep(1)
        job = api.call("GET", f"/api/jobs/{job['job_id']}")
    if job["status"] != "succeeded":
        raise SystemExit(f"Job {job['job_id']} ({job['kind']}) ended {job['status']}: {job.get('last_error')}")
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    api = Api(args.api)
    api.call("POST", "/api/auth/login", {"email": args.email, "password": args.password})
    print("signed in")

    api.call("POST", "/api/demo/seed-activity", {"scenario": "observed_browser_routine"})
    dna = api.call("GET", "/api/workflows/dna")["dna_items"]
    routine = next((d for d in dna if any(s.get("catalog_action") for s in d["invariant_steps"])), None)
    if routine is None:
        raise SystemExit("The sample activity did not produce an executable routine.")
    interpretation = api.call("POST", f"/api/workflows/{routine['dna_id']}/interpret?force_refresh=true")
    semantic_id = interpretation["semantic_workflow"]["semantic_workflow_id"]
    spec = api.call("POST", f"/api/workflows/{semantic_id}/specification")
    api.call("POST", f"/api/workflows/specifications/{spec['workflow_id']}/approve", {"reviewer": "smoke-test"})
    plan = api.call("POST", f"/api/workflows/specifications/{spec['workflow_id']}/execution-plan")
    print(f"workflow {spec['workflow_id']} approved, plan with {len(plan['planned_steps'])} steps")

    job = api.call("POST", f"/api/workflows/execution-plans/{plan['execution_plan_id']}/execute", {"execution_mode": "DRY_RUN"})
    job = wait_for_job(api, job)
    if job["side_effects_started"]:
        raise SystemExit("A dry run was recorded as having side effects.")
    record = api.call("GET", f"/api/workflows/executions/{job['result']['execution_id']}")
    steps = [s["status"] for s in record["step_results"]]
    if record["status"] != "COMPLETED" or any(s != "SUCCESS" for s in steps):
        raise SystemExit(f"Dry run did not complete: {record['status']} {steps} {record.get('error_summary')}")
    print(f"dry run finished by the worker: {len(steps)} steps succeeded")

    verification = wait_for_job(
        api, api.call("POST", f"/api/workflows/executions/{record['execution_id']}/verify", {"force_recheck": True})
    )
    print(f"verification job finished ({verification['result']['overall_status']})")
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
