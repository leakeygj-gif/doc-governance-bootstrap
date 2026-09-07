#!/usr/bin/env python3
"""词法存在性检查；不验证限定名归属、定义位置或规格语义。

退出码：0 无疑点（可能 NO_OBJECTS），1 有疑点，2 配置或读取错误。
Python 使用 tokenize 排除注释和字符串；其他语言仅匹配完整标识符，
其注释与字符串仍可能命中。README.md 是说明页，不作为规格扫描。
"""
import argparse
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR_CANDIDATES = ["tools", "assets/templates"]
SRC_EXTENSIONS = [".py"]
SKIP = {"None", "True", "False", "int", "str", "float", "dict", "list", "tuple", "bool", "self", "cls", "md", "json", "sh", "py"}
IDENT = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?)`")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--src", action="append")
    parser.add_argument("--ext", action="append")
    parser.add_argument("--specs", default="docs/specs")
    args = parser.parse_args()
    try:
        names = args.src or SRC_DIR_CANDIDATES
        dirs = [args.root / name for name in names if (args.root / name).is_dir()]
        if not dirs or (args.src and len(dirs) != len(names)):
            raise ValueError(f"找不到源码目录：{names}")
        specs = args.root / args.specs
        if not specs.is_dir():
            raise ValueError(f"找不到规格目录：{specs}")
        extensions = args.ext or SRC_EXTENSIONS
        if any(not ext.startswith('.') or len(ext) < 2 for ext in extensions):
            raise ValueError("源码后缀必须以 . 开头")
        files = sorted({p.resolve() for d in dirs for p in d.rglob('*') if p.is_file() and p.suffix in extensions})
        if not files:
            raise ValueError("配置源码目录内没有匹配后缀的文件")
        symbols = set()
        for path in files:
            if path.suffix == '.py':
                with tokenize.open(path) as stream:
                    source = stream.read()
                symbols.update(t.string for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type == tokenize.NAME)
            else:
                symbols.update(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', path.read_text(encoding='utf-8')))
        docs = sorted(p for p in specs.rglob('*.md') if p.name.lower() != 'readme.md')
        refs, findings = [], []
        for doc in docs:
            fence = None
            for number, line in enumerate(doc.read_text(encoding='utf-8').splitlines(), 1):
                marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
                if marker:
                    token = marker.group(1)
                    if fence is None:
                        fence = token
                    elif token[0] == fence[0] and len(token) >= len(fence):
                        fence = None
                    continue
                if fence:
                    continue
                for raw in IDENT.findall(line):
                    base = raw.removesuffix('()').split('.')[-1]
                    if base in SKIP or raw.endswith(tuple(extensions)):
                        continue
                    ref = (doc.relative_to(specs), number, raw)
                    refs.append(ref)
                    if base not in symbols:
                        findings.append(ref)
        print(f"源码文件={len(files)} 规格文件={len(docs)} 引用={len(refs)} 疑点={len(findings)}")
        for doc, number, raw in findings:
            print(f"疑点 {doc}:{number}: `{raw}`（请人工判断否定性描述等情况）")
        print('NO_OBJECTS 无可检查引用' if not refs else ('FINDINGS 需人工核查' if findings else 'OK 词法存在性检查通过'))
        return 1 if findings else 0
    except (OSError, UnicodeError, ValueError, SyntaxError, tokenize.TokenError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
