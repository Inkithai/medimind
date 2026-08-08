"""Offline tests for parent-job and independent child-document progress."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jobs  # noqa: E402


def test_files_can_be_in_different_phases_and_parent_updates_preserve_them():
    job = jobs.create_job("anon_progress_test", ["large-scan.pdf", "lab.jpg"])
    job_id = job["job_id"]
    try:
        jobs.update_job(job_id, status="processing", progress={"step": "extracting"})
        jobs.update_file_progress(
            job_id,
            1,
            status="processing",
            step="extracting",
            message="Finding medical details on page 2 of 8",
        )

        snapshot = jobs.get_job(job_id, "anon_progress_test")
        assert snapshot is not None
        first, second = snapshot["progress"]["files"]
        assert (first["status"], first["step"]) == ("processing", "extracting")
        assert (second["status"], second["step"]) == ("queued", "upload")

        # A parent-stage update is a patch. It must not erase child rows.
        jobs.update_job(job_id, progress={"step": "organizing", "message": "Updating history"})
        snapshot = jobs.get_job(job_id, "anon_progress_test")
        assert snapshot is not None
        assert snapshot["progress"]["step"] == "organizing"
        assert len(snapshot["progress"]["files"]) == 2
        assert snapshot["progress"]["files"][0]["step"] == "extracting"
    finally:
        with jobs._JOBS_LOCK:
            jobs._JOBS.pop(job_id, None)


def test_terminal_file_counters_are_recomputed_atomically():
    job = jobs.create_job("anon_counter_test", ["rx.pdf", "photo.jpg", "labs.pdf"])
    job_id = job["job_id"]
    try:
        jobs.update_file_progress(job_id, 1, status="completed", step="ready")
        jobs.update_file_progress(
            job_id,
            2,
            status="failed",
            step="failed",
            error="Temporarily busy",
            error_code="provider_rate_limited",
            retryable=True,
        )
        snapshot = jobs.get_job(job_id, "anon_counter_test")
        assert snapshot is not None
        progress = snapshot["progress"]
        assert progress["total_files"] == 3
        assert progress["processed_files"] == 2
        assert progress["successful_files"] == 1
        assert progress["failed_files"] == 1
        assert progress["files"][1]["error_code"] == "provider_rate_limited"
    finally:
        with jobs._JOBS_LOCK:
            jobs._JOBS.pop(job_id, None)


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
