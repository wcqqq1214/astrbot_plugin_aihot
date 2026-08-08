from __future__ import annotations

import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


class WorkflowConfigTests(unittest.TestCase):
    def test_quality_cache_path_uses_job_level_context(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "UV_CACHE_DIR: ${{ github.workspace }}/.uv-cache",
            workflow,
        )
        self.assertNotIn("UV_CACHE_DIR: ${{ runner.temp }}/uv-cache", workflow)


if __name__ == "__main__":
    unittest.main()
