"""Run evidence capture in disposable repositories; never touch project evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TASK = 'P03_20260907_漏检与证据保护验证'


class EvidencePreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'producer'
        self.target = self.base / 'target'
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', GIT_OPTIONAL_LOCKS='0',
                        GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        for path in (self.repo, self.target):
            path.mkdir()
            self.command(['git', 'init', '-q', str(path)])
            self.command(['git', '-C', str(path), 'commit', '--allow-empty', '-qm', 'fixture'])
        self.script = self.repo / 'tools/tasks' / TASK / 'review.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tools/tasks' / TASK / 'review.py', self.script)
        shutil.copyfile(ROOT / 'tools/task_pairs.py', self.repo / 'tools/task_pairs.py')
        tasks = self.target / 'docs/tasks'
        tasks.mkdir(parents=True)
        (tasks / 'P01_test.plan.md').write_text('**状态**：执行中\n')
        self.output = self.repo / 'data/tasks' / TASK

    def command(self, args):
        return subprocess.run(args, capture_output=True, text=True, env=self.env, check=True)

    def run_review(self, *args):
        return subprocess.run([sys.executable, str(self.script), '--target', str(self.target), *args],
                              capture_output=True, text=True, env=self.env)

    def tree(self, path):
        return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in path.rglob('*') if p.is_file()}

    def test_two_runs_and_default_refuses_overwrite(self):
        target_before = self.tree(self.target)
        first = self.run_review()
        self.assertEqual(first.returncode, 0, first.stderr)
        frozen = self.tree(self.output / 'default')
        duplicate = self.run_review()
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn('no overwrite', duplicate.stderr)
        self.assertEqual(frozen, self.tree(self.output / 'default'))
        second = self.run_review('--run-id', 'second')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(frozen, self.tree(self.output / 'default'))
        self.assertEqual(target_before, self.tree(self.target))
        for name in ('default', 'second'):
            manifest = json.loads((self.output / name / 'manifest.json').read_text())
            for artifact in manifest['artifacts']:
                self.assertEqual(artifact['sha256'], hashlib.sha256((self.repo / artifact['path']).read_bytes()).hexdigest())

    def test_invalid_checker_output_is_retained_and_not_overwritten(self):
        checker = self.base / 'broken.py'
        checker.write_text("print('not JSON')\nraise SystemExit(2)\n")
        result = self.run_review('--checker', str(checker))
        self.assertEqual(result.returncode, 2, result.stderr)
        data = json.loads((self.output / 'default/review-result.json').read_text())
        self.assertIsNone(data['checker'])
        self.assertEqual(data['returncode'], 2)
        frozen = self.tree(self.output)
        self.assertEqual(self.run_review().returncode, 2)
        self.assertEqual(frozen, self.tree(self.output))

    def test_invalid_run_id_creates_no_output(self):
        result = self.run_review('--run-id', '../escape')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
