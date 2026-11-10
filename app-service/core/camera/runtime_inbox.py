"""Bounded pending work; only unprocessed enrollment hellos may supersede peers."""

from datetime import datetime
from uuid import uuid4


def enqueue(state, action, value, now, until):
    jobs = state["jobs"]
    retained = []
    hello = action == "incoming" and value.get("type") == "camera_enrollment_hello"
    comparable = {
        k: v
        for k, v in value.items()
        if k not in ("enrollment_id", "admission_high_water")
    }
    duplicate = None
    for job in jobs:
        error = None
        old = job["value"]
        if datetime.fromisoformat(job["until"]) <= now:
            error = "camera_job_expired"
        elif (
            hello
            and job["action"] == "incoming"
            and comparable
            == {
                k: v
                for k, v in old.items()
                if k not in ("enrollment_id", "admission_high_water")
            }
        ):
            if value["admission_high_water"] < old["admission_high_water"]:
                raise ValueError("camera_hello_high_water_regressed")
            if value == old:
                duplicate = job["id"]
            else:
                error = "camera_job_superseded"
        if error:
            state["results"][job["id"]] = {"error": error}
            state["result_order"].append(job["id"])
        else:
            retained.append(job)
    state["jobs"] = retained
    while len(state["result_order"]) > 64:
        del state["results"][state["result_order"].pop(0)]
    if duplicate:
        return duplicate
    if len(retained) >= 64:
        raise ValueError("camera_inbox_busy")
    job_id = str(uuid4())
    retained.append(
        {"id": job_id, "action": action, "value": value, "until": until.isoformat()}
    )
    return job_id
