"""Keep the one-time migration cancellation confined to its verified target."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts import retire_legacy_simulation_run as retirement


ENVIRONMENT = {"GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": retirement.REPOSITORY,
               "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": "45847010996"}


def run_payload(status="in_progress"):
    return {"id": retirement.RUN_ID, "head_sha": retirement.HEAD_SHA,
            "head_branch": "main", "workflow_id": retirement.WORKFLOW_ID,
            "path": retirement.WORKFLOW_PATH, "name": retirement.WORKFLOW_NAME,
            "event": "push", "repository": {"full_name": retirement.REPOSITORY},
            "head_repository": {"full_name": retirement.REPOSITORY}, "status": status}


def response(payload=None, *, returncode=0, stdout=None):
    return subprocess.CompletedProcess([], returncode,
                                       stdout=json.dumps(payload) if stdout is None else stdout,
                                       stderr="fixture failure" if returncode else "")


class LegacyRunRetirementTests(unittest.TestCase):
    def cancel_calls(self, command):
        return [call for call in command.call_args_list if call.args[0][1:3] == ["run", "cancel"]]

    def test_completed_target_is_an_idempotent_noop(self):
        with mock.patch.object(retirement.subprocess, "run", return_value=response(run_payload("completed"))) as command:
            self.assertEqual(retirement.retire_legacy_run(ENVIRONMENT), "already_completed")
        self.assertEqual(command.call_count, 1)
        self.assertEqual(self.cancel_calls(command), [])

    def test_only_the_verified_active_legacy_target_is_cancelled(self):
        for status in retirement.ACTIVE_STATUSES:
            with self.subTest(status=status), mock.patch.object(retirement.subprocess, "run", side_effect=[
                    response(run_payload(status)), response(stdout="Cancellation requested")]) as command:
                self.assertEqual(retirement.retire_legacy_run(ENVIRONMENT), "cancellation_requested")
                self.assertEqual(command.call_args_list[0].args[0], [
                    "gh", "api", "--method", "GET",
                    f"repos/{retirement.REPOSITORY}/actions/runs/{retirement.RUN_ID}"])
                self.assertEqual(command.call_args_list[1].args[0], [
                    "gh", "run", "cancel", str(retirement.RUN_ID), "--repo", retirement.REPOSITORY])
                self.assertEqual(len(self.cancel_calls(command)), 1)

    def test_unrelated_or_quantum_run_identity_cannot_be_cancelled(self):
        replacements = {"id": 45843133409,
                        "head_sha": "8409d7e5629c3cd76dd8b17a9e1c057cfcba9b81",
                        "head_branch": "feature/other", "workflow_id": retirement.WORKFLOW_ID + 1,
                        "path": ".github/workflows/sync-draws.yml", "name": "Another workflow",
                        "event": "workflow_dispatch", "repository": {"full_name": "other/repository"},
                        "head_repository": {"full_name": "other/fork"}, "status": "unknown"}
        for field, replacement in replacements.items():
            payload = {**run_payload(), field: replacement}
            with self.subTest(field=field), mock.patch.object(retirement.subprocess, "run", return_value=response(payload)) as command:
                with self.assertRaises(retirement.RetirementError):
                    retirement.retire_legacy_run(ENVIRONMENT)
                self.assertEqual(command.call_count, 1)
                self.assertEqual(self.cancel_calls(command), [])

    def test_invalid_or_failed_initial_api_reads_never_cancel(self):
        cases = [response(returncode=1), response(stdout="not JSON"), response([]),
                 response({}), response({**run_payload(), "status": {"unexpected": True}}),
                 subprocess.TimeoutExpired("gh", 30), OSError("gh unavailable")]
        for case in cases:
            with self.subTest(case=str(case)), mock.patch.object(retirement.subprocess, "run", side_effect=[case]) as command:
                with self.assertRaises(retirement.RetirementError):
                    retirement.retire_legacy_run(ENVIRONMENT)
                self.assertEqual(command.call_count, 1)
                self.assertEqual(self.cancel_calls(command), [])

    def test_completion_race_requires_a_fresh_verified_completed_response(self):
        for failure in (response(returncode=1), subprocess.TimeoutExpired("gh", 30)):
            with self.subTest(failure=str(failure)), mock.patch.object(retirement.subprocess, "run", side_effect=[
                    response(run_payload()), failure, response(run_payload("completed"))]) as command:
                self.assertEqual(retirement.retire_legacy_run(ENVIRONMENT), "completed_during_cancellation")
                self.assertEqual(command.call_count, 3)
                self.assertEqual(len(self.cancel_calls(command)), 1)

    def test_unconfirmed_cancellation_fails_without_retrying_or_changing_target(self):
        reads = [response(run_payload()), response(returncode=1), response(stdout="not JSON"),
                 response({**run_payload("completed"), "id": 45843133409}),
                 response({**run_payload("completed"), "head_sha": "new-model-source"})]
        for final_read in reads:
            with self.subTest(final_read=str(final_read)), mock.patch.object(retirement.subprocess, "run", side_effect=[
                    response(run_payload()), response(returncode=1), final_read]) as command:
                with self.assertRaises(retirement.RetirementError):
                    retirement.retire_legacy_run(ENVIRONMENT)
                self.assertEqual(command.call_count, 3)
                self.assertEqual(len(self.cancel_calls(command)), 1)

    def test_only_push_and_manual_main_runs_can_attempt_retirement(self):
        for trigger in ("schedule", "workflow_run", "pull_request", ""):
            with self.subTest(trigger=trigger), mock.patch.object(retirement.subprocess, "run") as command:
                self.assertEqual(retirement.retire_legacy_run({**ENVIRONMENT, "GITHUB_EVENT_NAME": trigger}), "skipped_trigger")
                command.assert_not_called()
        for key, value in (("GITHUB_REPOSITORY", "other/repository"),
                           ("GITHUB_REF", "refs/heads/other"),
                           ("GITHUB_RUN_ID", str(retirement.RUN_ID))):
            with self.subTest(key=key), mock.patch.object(retirement.subprocess, "run") as command:
                with self.assertRaises(retirement.RetirementError):
                    retirement.retire_legacy_run({**ENVIRONMENT, key: value})
                command.assert_not_called()
        with mock.patch.object(retirement.subprocess, "run", return_value=response(run_payload("completed"))):
            self.assertEqual(retirement.retire_legacy_run({**ENVIRONMENT, "GITHUB_EVENT_NAME": "workflow_dispatch"}), "already_completed")

    def test_workflow_step_uses_its_existing_token_and_trigger_restriction(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/sync-draws.yml").read_text()
        step = workflow.split("      - name: Retire the pinned pre-quantum migration run\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn("if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'", step)
        self.assertIn("GH_TOKEN: ${{ github.token }}", step)
        self.assertIn("run: python scripts/retire_legacy_simulation_run.py", step)


if __name__ == "__main__":
    unittest.main()
