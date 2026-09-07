"""Task-local layouts preserve identity and exclude stored evidence."""
import unittest
import test_task_pairs


class LayoutTests(unittest.TestCase):
    setUp = test_task_pairs.PairTests.setUp
    check = test_task_pairs.PairTests.check
    codes = test_task_pairs.PairTests.codes
    def put(self, name, text=''):
        path = self.root / 'docs/tasks' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_mixed_layout_and_same_named_reports(self):
        self.put('P01_legacy.plan.md', '**状态**：已完成')
        self.put('P01_legacy.report.md')
        self.put('P02_one/plan.md', '**状态**：已完成')
        self.put('P02_one/report.md')
        self.put('P03_two/plan.md', '**状态**：已完成')
        result = self.check()
        self.assertEqual([(f['file'], f['code']) for f in result['findings']], [('P03_two/plan.md', 'missing_report')])
        self.assertEqual(result['plans'][1]['reports'], ['P02_one/report.md'])
        self.put('P03_two/report.md')
        self.assertEqual(self.codes(), set())

    def test_relative_stage_links_and_conflicts(self):
        self.put('P01_one/plan.md', '**状态**：已完成')
        self.put('P02_two/plan.md', '**状态**：执行中')
        self.put('P02_two/stage.report.md', '**对应计划**：[plan](../P01_one/plan.md)')
        self.assertEqual(self.codes(), set())
        self.put('P02_two/report.md', '**对应计划**：[plan](../P01_one/plan.md)')
        self.assertIn('conflicting_association', self.codes())
        self.put('P02_two/stage.report.md', '**对应计划**：[plan](missing/plan.md)')
        self.assertIn('missing_linked_plan', self.codes())

    def test_local_stage_index_and_missing_link(self):
        self.put('P01_one/plan.md', '**状态**：已完成')
        self.put('P01_one/phase.report.md')
        self.put('P01_one/index.md', '[p](plan.md) [r](phase.report.md)')
        self.assertEqual(self.codes(), set())
        self.put('P01_one/index.md', '[p](absent.plan.md)')
        self.assertIn('missing_index_plan', self.codes())
        self.put('P02_two/plan.md', '**状态**：执行中')
        self.put('P01_one/index.md', '[p](../P02_two/plan.md) [r](phase.report.md)')
        self.assertIn('ambiguous_index', self.codes())

    def test_nested_evidence_and_non_task_dirs_are_ignored(self):
        self.put('P01_one/plan.md', '**状态**：执行中')
        for name in ['P01_one/results/P99_fake.plan.md', 'P01_one/results/report.md', 'fixtures/P99_fake.plan.md', 'plan.md', 'report.md']:
            self.put(name, '**状态**：已完成')
        result = self.check()
        self.assertEqual(result['counts']['plans'], 1)
        self.assertEqual(result['counts']['reports'], 0)
        self.assertEqual(result['findings'], [])

    def test_nested_policy_exact_path(self):
        import json
        for name in ['P01_one/plan.md', 'P02_two/plan.md']:
            self.put(name, '**状态**：已完成')
        self.put('README.md', 'authorization')
        policy = {'version': 1, 'exemptions': [{'plan': 'P01_one/plan.md', 'reason': 'legacy', 'source': 'docs/tasks/README.md'}]}
        (self.root / 'policy.json').write_text(json.dumps(policy))
        result = self.check('policy.json')
        self.assertEqual([f['file'] for f in result['findings']], ['P02_two/plan.md'])
        policy['exemptions'][0]['plan'] = 'plan.md'
        (self.root / 'policy.json').write_text(json.dumps(policy))
        with self.assertRaises(ValueError):
            self.check('policy.json')

    def test_symlink_documents_and_directories_are_excluded(self):
        outside = self.root / 'P99_outside'
        outside.mkdir()
        (outside / 'plan.md').write_text('**状态**：已完成')
        tasks = self.root / 'docs/tasks'
        (tasks / 'P99_link').symlink_to(outside, target_is_directory=True)
        self.put('P01_one/plan.md', '**状态**：执行中')
        (tasks / 'P01_one/report.md').symlink_to(outside / 'plan.md')
        result = self.check()
        self.assertEqual(result['counts']['plans'], 1)
        self.assertEqual(result['counts']['reports'], 0)
        self.assertEqual(result['findings'], [])
