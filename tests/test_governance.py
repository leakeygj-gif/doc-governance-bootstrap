"""标准库行为测试；真实提交只发生在自动清理的临时 Git 仓库。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, content='value\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def run_tool(self, tool, *args, template=False):
        folder = 'assets/templates' if template else 'tools'
        return subprocess.run([sys.executable, str(ROOT / folder / tool), '--root', str(self.root), *args], capture_output=True, text=True)

    def git(self, *args):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(['git', '-C', str(self.root), *args], env=env, capture_output=True, text=True)

    def setup_git(self):
        self.assertEqual(self.git('init', '-q').returncode, 0)
        self.git('config', 'user.name', 'Governance test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.put('src/sample.py', 'original = 1\n')
        self.put('docs/HANDOFF.md')
        self.put('outside.txt', 'outside = 1\n')
        self.git('add', '.')
        self.assertEqual(self.git('commit', '-qm', 'baseline').returncode, 0)
        content = (ROOT / 'assets/templates/pre-commit').read_text().replace('{{SRC_GLOB}}', r'^src/.*\.py$')
        self.put('.githooks/pre-commit', content)
        (self.root / '.githooks/pre-commit').chmod(0o755)
        self.git('config', 'core.hooksPath', '.githooks')

    def test_hook_scenarios(self):
        for scenario in ['add', 'modify', 'delete', 'rename_out', 'rename_in', 'unstaged_log', 'deleted_log', 'with_log', 'docs_only']:
            with self.subTest(scenario=scenario):
                shutil.rmtree(self.root)
                self.root.mkdir()
                self.setup_git()
                if scenario in ['modify', 'unstaged_log', 'deleted_log', 'with_log']:
                    self.put('src/sample.py', 'changed = 2\n')
                    self.git('add', 'src/sample.py')
                elif scenario == 'add':
                    self.put('src/new.py'); self.git('add', 'src/new.py')
                elif scenario == 'delete':
                    self.git('rm', 'src/sample.py')
                elif scenario == 'rename_out':
                    self.git('mv', 'src/sample.py', 'moved.txt')
                elif scenario == 'rename_in':
                    self.git('mv', 'outside.txt', 'src/moved.py')
                else:
                    self.put('docs/guide.md'); self.git('add', 'docs/guide.md')
                if scenario in ['unstaged_log', 'with_log']:
                    self.put('docs/HANDOFF.md', 'new entry\n')
                    if scenario == 'with_log': self.git('add', 'docs/HANDOFF.md')
                if scenario == 'deleted_log': self.git('rm', 'docs/HANDOFF.md')
                result = self.git('commit', '-qm', scenario)
                self.assertEqual(result.returncode == 0, scenario in ['with_log', 'docs_only'], result.stdout + result.stderr)

    def test_repository_hook_guards_task_scripts(self):
        self.setup_git()
        self.put('.githooks/pre-commit', (ROOT / '.githooks/pre-commit').read_text())
        self.put('docs/tasks/P04_example/analyze.py', 'print("analysis")\n')
        self.git('add', 'docs/tasks/P04_example/analyze.py')
        result = self.git('commit', '-qm', 'task script')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('没有写交接日志', result.stdout + result.stderr)
        self.put('docs/HANDOFF.md', 'task script record\n')
        self.git('add', 'docs/HANDOFF.md')
        self.assertEqual(self.git('commit', '-qm', 'task script with record').returncode, 0)

    def test_symbols_all_dirs_and_token_boundaries(self):
        self.put('src/a.py', 'longer_name = 1\n# comment_only\ns = "string_only"\n')
        self.put('lib/b.py', 'actual = 1\n')
        self.put('docs/specs/README.md', '`ignored`')
        self.put('docs/specs/nested/spec.md', '`actual` `name` `comment_only` `string_only`')
        for template in [False, True]:
            result = self.run_tool('doc_symbols.py', '--src', 'src', '--src', 'lib', template=template)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('源码文件=2 规格文件=1 引用=4 疑点=3', result.stdout)

    def test_symbols_no_objects_success_and_errors(self):
        self.put('src/a.py', 'actual = 1\n')
        self.put('docs/specs/README.md', '`ignored`')
        result = self.run_tool('doc_symbols.py', '--src', 'src')
        self.assertEqual(result.returncode, 0)
        self.assertIn('NO_OBJECTS', result.stdout)
        self.put('docs/specs/spec.md', '`actual`\n~~~\n`missing`\n~~~')
        self.assertEqual(self.run_tool('doc_symbols.py', '--src', 'src').returncode, 0)
        self.assertEqual(self.run_tool('doc_symbols.py', '--src', 'absent').returncode, 2)
        self.assertEqual(self.run_tool('doc_symbols.py', '--src', 'src', '--ext', '.ts').returncode, 2)

    def test_task_pairs_full_prefix_and_status(self):
        self.put('docs/tasks/P01_phase1.plan.md', '**状态**：已完成')
        self.put('docs/tasks/P01_phase1.report.md')
        self.put('docs/tasks/P01_phase2.plan.md', '**状态**：已完成')
        for template in [False, True]:
            result = self.run_tool('task_pairs.py', template=template)
            self.assertEqual(result.returncode, 1)
            self.assertIn('P01_phase2.report.md', result.stdout)
        self.put('docs/tasks/P01_phase2.plan.md', '**状态**：执行中')
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 0)
        self.put('docs/tasks/orphan.report.md')
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 1)
        (self.root / 'docs/tasks/orphan.report.md').unlink()
        self.put('docs/tasks/P01_phase2.plan.md', '**状态**：未知')
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 1)

    def test_task_pairs_empty_and_config(self):
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 2)
        (self.root / 'docs/tasks').mkdir(parents=True)
        result = self.run_tool('task_pairs.py')
        self.assertEqual(result.returncode, 0)
        self.assertIn('NO_OBJECTS', result.stdout)

    def test_retest_report_explicitly_closes_plan(self):
        self.put('docs/tasks/P01_baseline.plan.md', '**状态**：已完成')
        self.put('docs/tasks/P01_round2.report.md', '**对应计划**：[原计划](P01_baseline.plan.md)')
        for template in [False, True]:
            result = self.run_tool('task_pairs.py', template=template)
            self.assertEqual(result.returncode, 0, result.stdout)
        self.put('docs/tasks/P01_baseline.report.md')
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 0)
        self.put('docs/tasks/P01_round2.report.md', '**对应计划**：[原计划](absent.plan.md)')
        self.assertEqual(self.run_tool('task_pairs.py').returncode, 1)

    def test_hook_invalid_configuration(self):
        self.setup_git()
        template = (ROOT / 'assets/templates/pre-commit').read_text()
        for pattern in ['{{SRC_GLOB}}', '[', '']:
            with self.subTest(pattern=pattern):
                self.put('.githooks/pre-commit', template.replace('{{SRC_GLOB}}', pattern))
                result = subprocess.run(['sh', '.githooks/pre-commit'], cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('ERROR', result.stderr)

    def test_template_parity(self):
        actual = (ROOT / 'tools/doc_symbols.py').read_text().replace('["tools", "assets/templates"]', '["src", "lib", "app"]')
        self.assertEqual(actual, (ROOT / 'assets/templates/doc_symbols.py').read_text())
        self.assertEqual((ROOT / 'tools/task_pairs.py').read_text(), (ROOT / 'assets/templates/task_pairs.py').read_text())
        import re
        normalize = lambda path: re.sub(r'^SRC_PATTERN=.*$', 'SRC_PATTERN=CONFIG', path.read_text(), flags=re.M)
        self.assertEqual(normalize(ROOT / '.githooks/pre-commit'), normalize(ROOT / 'assets/templates/pre-commit'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
