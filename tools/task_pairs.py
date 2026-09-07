#!/usr/bin/env python3
"""检查任务状态及明确的计划/报告关联。0 无疑点，1 MISSING/REVIEW，2 配置错误。"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
STATES = {'草拟中', '已确认', '执行中', '搁置', '已废弃', '已完成'}
LINK = re.compile(r'\[[^\]\n]*\]\(([^)\n]+)\)')


def visible(text, strip_inline=True):
    """Ignore Markdown examples/comments before interpreting metadata or links."""
    text = re.sub(r'<!--.*?(?:-->|\Z)', '', text, flags=re.S)
    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(re.sub(r'(`+).*?\1', '', line) if strip_inline else line)
    return '\n'.join(lines)


def fields(text, name):
    return re.findall(r'^\*\*' + name + r'\*\*\s*[：:]\s*(.*?)\s*$', text, re.M)


def local_target(base, value):
    return (base / unquote(value.split('#', 1)[0])).resolve()


def check(root, tasks, policy=None):
    root = root.resolve()
    directory = (root / tasks).resolve()
    if not directory.is_dir():
        raise ValueError(f'找不到任务目录：{directory}')
    # Only task documents at approved levels; never recurse into evidence/fixtures.
    files = [p for p in directory.iterdir() if p.is_file() and not p.is_symlink()]
    for folder in directory.iterdir():
        if folder.is_dir() and not folder.is_symlink() and re.match(r'^P\d+_', folder.name):
            files.extend(p for p in folder.iterdir() if p.is_file() and not p.is_symlink())

    def key(path):
        return path.relative_to(directory).as_posix()

    def is_plan(path):
        return path.name.endswith('.plan.md') or (path.parent != directory and path.name == 'plan.md')

    def is_report(path):
        return path.name.endswith('.report.md') or (path.parent != directory and path.name == 'report.md')

    def project_id(path):
        label = path.relative_to(directory).parts[0] if path.is_relative_to(directory) else ''
        match = re.match(r'P\d+(?=_)', label)
        return match.group() if match else None

    plans = {key(p): p for p in files if is_plan(p)}
    reports = {key(p): p for p in files if is_report(p)}
    plan_paths = {p.resolve(): name for name, p in plans.items()}
    report_paths = {p.resolve(): name for name, p in reports.items()}
    indexes = [p for p in files if p.name.endswith('.index.md') or
               (p.parent != directory and p.name == 'index.md')]
    exemptions = {}
    if policy:
        document = json.loads((root / policy).read_text(encoding='utf-8'))
        if not isinstance(document, dict) or set(document) != {'version', 'exemptions'} or type(document['version']) is not int or document['version'] != 1 or not isinstance(document['exemptions'], list):
            raise ValueError('policy 需要 version=1 和 exemptions 数组')
        for item in document['exemptions']:
            if not isinstance(item, dict) or set(item) != {'plan', 'reason', 'source'} or any(not isinstance(v, str) or not v.strip() for v in item.values()):
                raise ValueError('每项豁免需要非空 plan/reason/source 字符串')
            if item['plan'] not in plans or item['plan'] in exemptions:
                raise ValueError(f'豁免计划不存在或重复：{item["plan"]}')
            source = local_target(root, item['source'])
            if not source.is_relative_to(root) or not source.is_file():
                raise ValueError(f'豁免来源必须是仓库内现存文件：{item["source"]}')
            exemptions[item['plan']] = item
    findings, associations = [], []
    candidates = {name: set() for name in reports}
    invalid = set()

    def issue(category, code, file, message):
        findings.append(dict(category=category, code=code, file=file, message=message))

    def associate(report, plan, via):
        candidates[report].add(plan)
        associations.append(dict(report=report, plan=plan, via=via))

    for name, path in sorted(reports.items()):
        same = key(path.with_name('plan.md')) if path.name == 'report.md' else name.removesuffix('.report.md') + '.plan.md'
        if same in plans:
            associate(name, same, 'same_prefix')
        values = fields(visible(path.read_text(encoding='utf-8')), '(?:对应计划|计划)')
        if values:
            links = [LINK.fullmatch(value) for value in values]
            if len(values) != 1 or any(link is None for link in links):
                issue('REVIEW', 'invalid_plan_field', name, '计划元数据必须且只能有一个 Markdown 链接')
                invalid.add(name)
            else:
                target = local_target(path.parent, links[0].group(1))
                if target not in plan_paths:
                    issue('MISSING', 'missing_linked_plan', name, '对应计划链接无效或文件不存在')
                    invalid.add(name)
                else:
                    associate(name, plan_paths[target], 'metadata')
    for index in sorted(indexes):
        content = visible(index.read_text(encoding='utf-8'))
        targets = [local_target(index.parent, value) for value in LINK.findall(content)]
        project = project_id(index)
        groups = [targets]
        if len({p for p in targets if is_plan(p)}) > 1:
            groups = [[local_target(index.parent, value) for value in LINK.findall(line)]
                      for line in content.splitlines() if line.strip().startswith('|')]
            groups = [group for group in groups if any(is_plan(p) or is_report(p) for p in group)]
            covered = {p for group in groups for p in group}
            if any(p not in covered for p in targets if is_plan(p) or is_report(p)):
                groups.append([p for p in targets if p not in covered])
        for group in groups:
            linked_plans = {p for p in group if is_plan(p)}
            linked_reports = {p for p in group if is_report(p)}
            for target in sorted(linked_plans):
                if target not in plan_paths:
                    issue('MISSING', 'missing_index_plan', key(index), f'索引计划链接无效或文件不存在：{target}')
            if not linked_reports:
                continue
            valid = project and len(linked_plans) == 1 and all(
                p in plan_paths and project_id(p) == project for p in linked_plans) and all(
                p in report_paths and project_id(p) == project for p in linked_reports)
            if not valid:
                issue('REVIEW', 'ambiguous_index', key(index), '索引或表格行需同项目、恰好一个现存计划及现存报告链接；请明确关系')
                invalid.update(report_paths[p] for p in linked_reports if p in report_paths)
                continue
            for report in sorted(linked_reports):
                associate(report_paths[report], plan_paths[next(iter(linked_plans))], key(index))
    accepted = {name: [] for name in plans}
    for name, linked in sorted(candidates.items()):
        if len(linked) > 1:
            issue('REVIEW', 'conflicting_association', name, '同名、元数据或索引指向不同计划：' + ', '.join(sorted(linked)))
        elif len(linked) == 1 and name not in invalid:
            accepted[next(iter(linked))].append(name)
        elif not linked and name not in invalid:
            issue('MISSING', 'missing_plan', name, '缺少同前缀 plan 或明确关联')
    records = []
    for name, path in sorted(plans.items()):
        content = visible(path.read_text(encoding='utf-8'), strip_inline=False)
        values = fields(content, '状态')
        raw = values[0] if len(values) == 1 else ' | '.join(values)
        state = next((s for s in STATES if re.fullmatch(re.escape(s) + r'(?:\s*[；;，,：（(].*)?', raw)), None) if len(values) == 1 else None
        if len(values) != 1 or not state:
            issue('REVIEW', 'unknown_state', name, f'状态缺失、多值或自由描述，需人工确认：{raw!r}')
        if state and re.search(r'(?:^|[；;，,])\s*(?:状态\s*[：:]\s*)?(' + '|'.join(STATES - {state}) + r')(?=$|[；;，,：（(\s])', raw[len(state):]):
            issue('REVIEW', 'conflicting_state', name, '状态说明包含另一规范状态，需人工确认')
            state = None
        if state == '已完成' and not accepted[name] and name not in exemptions:
            expected = key(path.with_name('report.md')) if path.name == 'plan.md' else name.removesuffix('.plan.md') + '.report.md'
            issue('MISSING', 'missing_report', name, f'已完成但缺少 {expected} 或有效关联报告')
        records.append(dict(file=name, state_raw=raw, state=state, acceptance_boundary=fields(content, '验收边界'), reports=accepted[name], exemption=exemptions.get(name)))
    counts = dict(plans=len(plans), reports=len(reports), missing=sum(f['category'] == 'MISSING' for f in findings), review=sum(f['category'] == 'REVIEW' for f in findings), findings=len(findings))
    return dict(schema_version=1, counts=counts, plans=records, associations=associations, findings=findings, result='FINDINGS' if findings else ('NO_OBJECTS' if not plans and not reports else 'OK'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--tasks', default='docs/tasks')
    parser.add_argument('--policy', help='显式历史豁免 JSON，可为外部绝对路径或相对于 root 的路径')
    parser.add_argument('--json', action='store_true', help='输出机器可读结果')
    args = parser.parse_args()
    try:
        result = check(args.root, args.tasks, args.policy)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for item in result['findings']:
                print(f'{item["category"]} {item["file"]}: {item["message"]}')
            counts = result['counts']
            print(f'计划={counts["plans"]} 报告={counts["reports"]} 疑点={counts["findings"]} MISSING={counts["missing"]} REVIEW={counts["review"]}')
            print(result['result'])
        return 1 if result['findings'] else 0
    except (OSError, UnicodeError, ValueError) as exc:
        if args.json:
            print(json.dumps(dict(result='ERROR', error=str(exc)), ensure_ascii=False))
        else:
            print(f'ERROR {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
