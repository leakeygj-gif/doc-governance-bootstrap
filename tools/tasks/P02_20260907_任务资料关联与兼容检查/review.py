#!/usr/bin/env python3
"""Read-only target review; outputs only into this repository's matching task directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).parent.name


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, env=env, check=True)
    return result.stdout


def snapshot(root):
    paths = [p for p in (root / 'docs').rglob('*') if p.is_file()]
    paths += [root / 'AGENTS.md', root / '.githooks/pre-commit']
    files = {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(set(paths)) if p.is_file()}
    git_dir = Path(git(root, 'rev-parse', '--absolute-git-dir').decode().strip())
    return {
        'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
        'branch': git(root, 'branch', '--show-current').decode().strip(),
        'status_sha256': sha(git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')),
        'effective_config_sha256': sha(git(root, 'config', '--null', '--list', '--show-origin')),
        'git_files_sha256': {name: sha((git_dir / name).read_bytes()) if (git_dir / name).exists() else None for name in ['config', 'index']},
        'documents_sha256': files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--policy', type=Path, help='Optional policy stored in this task output directory')
    args = parser.parse_args()
    target = args.target.resolve()
    if target == ROOT:
        parser.error('Use a separate read-only target repository')
    destination = ROOT / 'data/tasks' / TASK
    destination.mkdir(parents=True, exist_ok=True)
    before = snapshot(target)
    command = [sys.executable, str(ROOT / 'tools/task_pairs.py'), '--root', str(target), '--json']
    if args.policy:
        if args.policy.resolve().parent != destination:
            parser.error('Policy must be in this task output directory')
        command += ['--policy', str(args.policy.resolve())]
    run = subprocess.run(command, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', GIT_OPTIONAL_LOCKS='0'))
    after = snapshot(target)
    try:
        payload = json.loads(run.stdout)
    except json.JSONDecodeError:
        payload = None
    result = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'target': str(target), 'command': command, 'returncode': run.returncode,
        'checker': payload, 'stdout': run.stdout, 'stderr': run.stderr,
        'target_unchanged': before == after, 'before': before, 'after': after,
        'limitations': ['No business tests or hardware operations.', 'Document hashes identify this local sample; raw scan data were not copied or checked.', 'Status, config, index and selected document hashes cannot prove the absence of unrelated concurrent activity.'],
    }
    output = destination / ('review-result-policy.json' if args.policy else 'review-result.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    paths = [Path(__file__).resolve(), ROOT / 'tools/task_pairs.py', output]
    roles = ['任务专用复核脚本', '共享任务检查器', '检查输出及前后快照']
    if args.policy:
        paths += [args.policy.resolve(), destination / 'review-result.json']
        roles += ['有来源的历史缺报告豁免输入', '无策略原始检查结果']
    manifest = {
        'task': TASK, 'purpose': '复核新版任务检查器在外部项目中的实际兼容性，保留未解决疑点与只读边界证据。',
        'plan': 'docs/tasks/' + TASK + '.plan.md', 'report': 'docs/tasks/' + TASK + '.report.md',
        'command': command, 'reproduce': [sys.executable, str(Path(__file__).resolve()), '--target', str(target)] + (['--policy', str(args.policy.resolve())] if args.policy else []),
        'input': {'repository': str(target), 'head': before['head'], 'document_hash_list': output.name + ':before.documents_sha256'},
        'artifacts': [{'path': str(p.relative_to(ROOT)), 'purpose': role,
                       'role': 'script' if p.suffix == '.py' else ('input' if p.name == 'legacy-policy.json' else 'output'),
                       'parameters': {'command': command} if p.suffix == '.py' else {},
                       'inputs': [str(target) + '/docs/tasks'] if p.suffix == '.py' else [],
                       'outputs': [str(output.relative_to(ROOT))] if p.suffix == '.py' else [],
                       'sha256': sha(p.read_bytes()),
                       'storage': {'local_exists': True,
                                   'git_tracked': bool(git(ROOT, 'ls-files', '--', str(p.relative_to(ROOT))).strip()),
                                   'external_archive_verified': False}}
                      for p, role in zip(paths, roles)],
        'preservation_status': '本地生成，非云备份；原始扫描数据未复制。',
    }
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'returncode': run.returncode, 'target_unchanged': before == after, 'result': str(output), 'json_valid': payload is not None}, ensure_ascii=False))
    return 0 if before == after and payload is not None and run.returncode in (0, 1) else 2


if __name__ == '__main__':
    sys.exit(main())
