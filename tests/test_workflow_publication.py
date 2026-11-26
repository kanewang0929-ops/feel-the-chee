"""Exercise the real publication shell against a temporary local Git remote."""
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def publication_script():
    workflow = (ROOT / ".github/workflows/sync-draws.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Commit draw database, forecasts, agent states, and audit ledgers\n", 1)[1]
    block = step.split("        run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


class WorkflowPublicationTests(unittest.TestCase):
    def test_archive_formula_and_agents_publish_together(self):
        outputs = [
            "data/draws.json", "data/chee-forecast.json", "data/chee-backtest.json",
            "data/joy-kane-dashboard.json", "data/joy-kane-model-state.json",
            "data/joy-kane-live-lock.json", "data/joy-kane-predictions.jsonl",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, checkout = root / "origin.git", root / "checkout"
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

            def git(*args, cwd=root):
                return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()

            git("init", "--bare", "--initial-branch=main", str(remote))
            git("clone", str(remote), str(checkout))
            git("config", "user.name", "Publication test", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            for path in [*outputs, "data/unrelated.json"]:
                file = checkout / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('"old"\n', encoding="utf-8")
            git("add", ".", cwd=checkout)
            git("commit", "-m", "Initial fixture", cwd=checkout)
            git("push", "origin", "main", cwd=checkout)
            for path in [*outputs, "data/unrelated.json"]:
                (checkout / path).write_text('"new"\n', encoding="utf-8")

            subprocess.run(["bash", "-e", "-o", "pipefail", "-c", publication_script()],
                           cwd=checkout, env=env, check=True, capture_output=True, text=True)

            changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", "main", cwd=remote).splitlines()
            self.assertEqual(sorted(changed), sorted(outputs))
            for path in outputs:
                self.assertEqual(git("show", f"main:{path}", cwd=remote), '"new"')
            self.assertEqual(git("show", "main:data/unrelated.json", cwd=remote), '"old"')


if __name__ == "__main__":
    unittest.main()
