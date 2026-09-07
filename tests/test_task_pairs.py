"""Synthetic evidence relationships; no target project writes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pairs', Path(__file__).resolve().parents[1] / 'tools/task_pairs.py')
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)


class PairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'docs/tasks').mkdir(parents=True)

    def put(self, name, text=''):
        (self.root / 'docs/tasks' / name).write_text(text)

    def check(self, policy=None):
        return pairs.check(self.root, 'docs/tasks', policy)

    def codes(self):
        return {x['code'] for x in self.check()['findings']}

    def test_state_boundary_and_freeform(self):
        self.put('P01_a.plan.md', '**状态**：已完成；本次离线验证通过\n**验收边界**：实机待验 `gain=0`')
        self.put('P01_a.report.md')
        result = self.check()
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['plans'][0]['acceptance_boundary'], ['实机待验 `gain=0`'])
        self.put('P01_a.plan.md', '**状态**：验证已收口；连续扫描未通过')
        self.assertEqual(self.codes(), {'unknown_state'})
        self.put('P01_a.plan.md', '**状态**：已完成；执行中')
        self.assertIn('conflicting_state', self.codes())
        self.put('P01_a.plan.md', '**状态**：已完成\n**状态**：执行中')
        self.assertIn('unknown_state', self.codes())

    def test_metadata_conflict_and_missing(self):
        self.put('P01_a.plan.md', '**状态**：已完成')
        self.put('P01_b.plan.md', '**状态**：执行中')
        self.put('P01_a.report.md', '**计划**：[B](P01_b.plan.md)')
        self.assertEqual(self.codes(), {'conflicting_association', 'missing_report'})
        self.put('P01_a.report.md', '**对应计划**：[x](missing.plan.md)')
        self.assertIn('missing_linked_plan', self.codes())
        self.assertIn('missing_report', self.codes())

    def test_stages_do_not_hide_other_missing_plan(self):
        self.put('P01_a.plan.md', '**状态**：已完成')
        self.put('P01_b.plan.md', '**状态**：已完成')
        self.put('P01_round2.report.md', '**对应计划**：[A](P01_a.plan.md)')
        result = self.check()
        self.assertEqual([(f['file'], f['code']) for f in result['findings']], [('P01_b.plan.md', 'missing_report')])
        self.assertEqual(result['plans'][0]['reports'], ['P01_round2.report.md'])

    def test_index_table_explicit_rows_and_ambiguity(self):
        for stem in ['a', 'b']:
            self.put(f'P01_{stem}.plan.md', '**状态**：已完成')
            self.put(f'P01_{stem}_stage.report.md')
        self.put('P01_map.index.md', '| [a](P01_a.plan.md) | [ar](P01_a_stage.report.md) |\n| [b](P01_b.plan.md) | [br](P01_b_stage.report.md) |')
        self.assertEqual(self.codes(), set())
        self.put('P01_map.index.md', '[a](P01_a.plan.md) [b](P01_b.plan.md)\n[ar](P01_a_stage.report.md) [br](P01_b_stage.report.md)')
        self.assertIn('ambiguous_index', self.codes())
        self.assertIn('missing_report', self.codes())

    def test_index_missing_plan_without_report_is_not_silent(self):
        self.put('P01_map.index.md', '[missing](P01_absent.plan.md)')
        result = self.check()
        self.assertEqual(result['result'], 'FINDINGS')
        self.assertEqual(self.codes(), {'missing_index_plan'})
        self.assertEqual(result['counts']['missing'], 1)

    def test_index_plan_only_rows_validate_links_without_requiring_reports(self):
        self.put('P01_a.plan.md', '**状态**：已完成')
        self.put('P01_a_stage.report.md')
        self.put('P01_b.plan.md', '**状态**：执行中')
        index = '| [a](P01_a.plan.md) | [r](P01_a_stage.report.md) |\n| [b](P01_b.plan.md) | |'
        self.put('P01_map.index.md', index)
        self.assertEqual(self.codes(), set())
        self.put('P01_map.index.md', index + '\n| [missing](P01_absent.plan.md) | |')
        self.assertEqual(self.codes(), {'missing_index_plan'})
        self.assertEqual(self.check()['plans'][0]['reports'], ['P01_a_stage.report.md'])

    def test_index_plan_link_must_target_tasks_directory(self):
        self.put('P01_a.plan.md', '**状态**：执行中')
        (self.root / 'P01_a.plan.md').write_text('**状态**：执行中')
        self.put('P01_map.index.md', '[outside](../../P01_a.plan.md)')
        self.assertEqual(self.codes(), {'missing_index_plan'})

    def test_policy_exact_scope_and_validation(self):
        for stem in ['a', 'b']:
            self.put(f'P01_{stem}.plan.md', '**状态**：已完成')
        self.put('README.md', '历史豁免依据')
        policy = {'version': 1, 'exemptions': [{'plan': 'P01_a.plan.md', 'reason': '历史授权', 'source': 'docs/tasks/README.md'}]}
        path = self.root / 'policy.json'
        path.write_text(json.dumps(policy))
        result = self.check('policy.json')
        self.assertEqual([f['file'] for f in result['findings']], ['P01_b.plan.md'])
        policy['exemptions'][0]['source'] = 'absent.md'
        path.write_text(json.dumps(policy))
        with self.assertRaises(ValueError):
            self.check('policy.json')
        self.assertEqual(len(self.check()['findings']), 2)

    def test_examples_cannot_create_evidence(self):
        self.put('P01_a.plan.md', '**状态**：已完成')
        self.put('P01_stage.report.md', '```md\n**对应计划**：[a](P01_a.plan.md)\n```\n<!-- **对应计划**：[a](P01_a.plan.md) -->\n`**对应计划**：[a](P01_a.plan.md)`')
        self.put('P01_map.index.md', '~~~md\n[a](P01_a.plan.md) [r](P01_stage.report.md)\n~~~')
        self.assertEqual(self.codes(), {'missing_plan', 'missing_report'})
        self.put('P01_a.plan.md', '```\n**状态**：已完成\n```')
        self.assertIn('unknown_state', self.codes())

    def test_body_links_are_not_metadata(self):
        self.put('P01_a.plan.md', '**状态**：已完成')
        self.put('P01_stage.report.md', '另见[历史](P01_a.plan.md)')
        self.assertEqual(self.codes(), {'missing_plan', 'missing_report'})


if __name__ == '__main__':
    unittest.main()
