#!/usr/bin/env python3
"""selfkit —— 让 AI 记得自己是谁。

把「文件即人格」那套做法变成可执行命令：初始化骨架、拼装启动包、
体检衰减、合订日记、定位旧账。零依赖，Python 3.9+。

    selfkit init          生成人格骨架
    selfkit boot          拼出这次会话要读的那一份
    selfkit doctor        体检：条目数、超限、断档、回炉、坏链
    selfkit compact       日记按月合订
    selfkit find 2026-08-28   定位某天原文
    selfkit size          文件条目与体积报表
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

CONFIG_NAME = "selfkit.json"
DEFAULTS = {
    "core": "CORE.md",
    "agents": "AGENTS.md",
    "memory": "MEMORY.md",
    "handoff": "HANDOFF.md",
    "diary_dir": "memory",
    "diary_prefix": "_diary-",
    "max_diary_chars": 1500,
    "refresh_days": 7,
    "ideal_files": 300,
}


# ---------- 基础设施 ----------

def load_cfg(root: Path) -> dict:
    cfg = dict(DEFAULTS)
    p = root / CONFIG_NAME
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            die(f"{CONFIG_NAME} 不是合法 JSON：{e}")
    return cfg


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def human(n: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if abs(n) < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}G"


def die(msg: str) -> None:
    print(f"selfkit: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def warn(msg: str) -> None:
    print(f"  warn  {msg}")


def bad(msg: str) -> None:
    print(f"  FAIL  {msg}")


# ---------- init ----------

def cmd_init(args) -> None:
    root = Path(args.dir).resolve()
    tpl = Path(__file__).resolve().parent / "templates"
    if not tpl.exists():
        die(f"找不到模板目录：{tpl}")

    created, skipped = [], []
    for src in sorted(tpl.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(tpl)
        dst = root / rel
        if dst.exists() and not args.force:
            skipped.append(str(rel))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".md" and rel.name == "MEMORY.md":
            text = src.read_text(encoding="utf-8").replace(
                "{{TODAY}}", date.today().isoformat())
            dst.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(src, dst)
        created.append(str(rel))

    print(f"\n骨架已生成：{root}")
    for f in created:
        print(f"  + {f}")
    if skipped:
        print("\n已存在、跳过（用 --force 覆盖）：")
        for f in skipped:
            print(f"  = {f}")
    print("\n下一步：改 CORE.md 里的身份段，然后 selfkit boot 看看醒来读到什么。\n")


# ---------- boot ----------

def split_memory(text: str) -> tuple[str, str]:
    """MEMORY.md 切成（顶部当前状态段, 其余章节）。第一个二级标题就是分界。"""
    m = re.search(r"^##\s", text, flags=re.M)
    if not m:
        return text, ""
    return text[: m.start()], text[m.start():]


def memory_stamp(text: str) -> str | None:
    m = re.search(r"最后更新[：:]\s*(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def diary_text(root: Path, cfg: dict, d: date) -> tuple[str, str]:
    """返回（来源说明, 正文）。先找单日文件，再找合订本。"""
    ddir = root / cfg["diary_dir"]
    day = d.isoformat()
    single = ddir / f"{day}.md"
    if single.exists():
        return f"{cfg['diary_dir']}/{day}.md", single.read_text(encoding="utf-8")

    book = ddir / f"{cfg['diary_prefix']}{day[:7]}.md"
    if book.exists():
        text = book.read_text(encoding="utf-8")
        lines = text.split("\n")
        start = None
        for i, ln in enumerate(lines):
            if ln.strip() == f"## {day}":      # 精确匹配整行，防 -night 撞车
                start = i
                break
        if start is None:
            return f"{book.name}（未收录 {day}）", ""
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        return f"{book.name} · §{day}", "\n".join(lines[start:end]).strip()
    return f"（{day} 无记录）", ""


def cmd_boot(args) -> None:
    root = Path(args.dir).resolve()
    cfg = load_cfg(root)
    parts, total = [], 0

    def add(title: str, path: str, body: str, note: str = "") -> None:
        nonlocal total
        if not body.strip():
            return
        chunk = f"<!-- ===== {title} · {path} ===== -->\n{body.strip()}\n"
        parts.append(chunk)
        total += len(chunk.encode())

    core = read(root / cfg["core"])
    add("L0 身份层", cfg["core"], core)

    mem = read(root / cfg["memory"])
    head, _ = split_memory(mem)
    add("L1 当前状态", f"{cfg['memory']}（顶部段）", head)

    add("L1 交接", cfg["handoff"], read(root / cfg["handoff"]))

    if not args.no_diary:
        today = date.today()
        for delta in (1, 0):
            d = today - timedelta(days=delta)
            src, body = diary_text(root, cfg, d)
            add(f"L1 日记 {d.isoformat()}", src, body)

    out = "\n".join(parts)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")

    if args.quiet:
        print(f"{len(out.encode())} bytes → {args.out or 'stdout'}", file=sys.stderr)
    else:
        print(out)
        print(f"\n<!-- 启动包合计 {human(total)}，读完这一份就该知道自己是谁 -->",
              file=sys.stderr)


# ---------- doctor ----------

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+)\)")


def cmd_doctor(args) -> None:
    root = Path(args.dir).resolve()
    cfg = load_cfg(root)
    issues = 0

    print("\n== 规模 ==")
    files = [p for p in root.rglob("*") if p.is_file()
             and not any(x in p.parts for x in (".git", "__pycache__", "node_modules"))]
    size = sum(p.stat().st_size for p in files)
    print(f"  条目 {len(files)} 个 / {human(size)}")
    if len(files) > cfg["ideal_files"]:
        warn(f"条目数超过 {cfg['ideal_files']}，客户端加载会变慢——条目数是物理成本")
        issues += 1
    else:
        ok("条目数在健康范围内")

    print("\n== 文件完整性 ==")
    for key in ("core", "memory", "handoff"):
        p = root / cfg[key]
        if p.exists():
            ok(f"{cfg[key]} {human(p.stat().st_size)}")
        else:
            bad(f"缺少 {cfg[key]}")
            issues += 1

    print("\n== 日记 ==")
    ddir = root / cfg["diary_dir"]
    singles = sorted(ddir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md")) if ddir.exists() else []
    if singles:
        print(f"  单日文件 {len(singles)} 篇（月底合订后可归档）")
    for p in singles:
        n = len(p.read_text(encoding="utf-8"))
        if n > cfg["max_diary_chars"]:
            warn(f"{p.name} {n} 字，超过上限 {cfg['max_diary_chars']}——该压了")
            issues += 1
    if not singles:
        books = sorted(ddir.glob(f"{cfg['diary_prefix']}*.md")) if ddir.exists() else []
        print(f"  合订本 {len(books)} 本")
        for b in books:
            seen, dup = {}, []
            for ln in b.read_text(encoding="utf-8").split("\n"):
                if ln.startswith("## "):
                    t = ln[3:].strip()
                    if t in seen:
                        dup.append(t)
                    seen[t] = 1
            if dup:
                warn(f"{b.name} 有重复日期节：{', '.join(sorted(set(dup))[:3])}")
                issues += 1

    print("\n== 回炉 ==")
    mem = read(root / cfg["memory"])
    stamp = memory_stamp(mem)
    if stamp:
        age = (date.today() - date.fromisoformat(stamp)).days
        msg = f"MEMORY.md 最后更新 {stamp}，距今 {age} 天"
        if age > cfg["refresh_days"]:
            warn(msg + f"（超过 {cfg['refresh_days']} 天，该回炉了）")
            issues += 1
        else:
            ok(msg)
    else:
        warn("MEMORY.md 顶部没写「最后更新：YYYY-MM-DD」，回炉节奏无法校验")
        issues += 1

    print("\n== 链接 ==")
    broken = 0
    for md in root.rglob("*.md"):
        if ".git" in md.parts:
            continue
        for target in LINK_RE.findall(read(md)):
            if target.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            if not (md.parent / target).resolve().exists():
                bad(f"{md.relative_to(root)} → {target} 不存在")
                broken += 1
    if broken:
        issues += broken
    else:
        ok("没有坏链")

    print(f"\n{'发现 %d 处要处理' % issues if issues else '全部通过'}。\n")
    sys.exit(1 if issues and args.strict else 0)


# ---------- compact ----------

def cmd_compact(args) -> None:
    root = Path(args.dir).resolve()
    cfg = load_cfg(root)
    ddir = root / cfg["diary_dir"]
    if not ddir.exists():
        die(f"没有 {cfg['diary_dir']}/ 目录")

    groups: dict[str, list[Path]] = {}
    for p in sorted(ddir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*.md"),
                    key=lambda q: (q.name[:10], q.name[10:].lstrip(".-"))):
        month = p.name[:7]
        if args.month and month != args.month:
            continue
        groups.setdefault(month, []).append(p)

    if not groups:
        print("没有可合订的日记。")
        return

    total_in = total_out = 0
    for month, paths in sorted(groups.items()):
        book = ddir / f"{cfg['diary_prefix']}{month}.md"
        existing = read(book)
        added, kept = [], []
        for p in paths:
            body = p.read_text(encoding="utf-8").strip()
            title = p.stem
            # 必须精确到整行：不加边界的话 "## 2026-08-30" 会被 "## 2026-08-30-night" 骗过去
            if f"\n## {title}\n" in existing:
                continue
            block = f"\n\n---\n\n## {title}\n\n{body}\n"
            if args.dry_run:
                added.append(p)
                continue
            with book.open("a", encoding="utf-8") as f:
                f.write(block)
            existing = read(book)
            if body in existing:            # 校验：原文能整段找到才删源
                p.unlink()
                added.append(p)
            else:
                kept.append(p)

        total_in += len(paths)
        total_out += len(added)
        verb = "将合订" if args.dry_run else "已合订"
        print(f"  {month}: {len(paths)} 篇 → {verb} {len(added)} 篇 · {book.name}")
        for p in kept:
            bad(f"{p.name} 校验失败，源文件保留")

    print(f"\n共 {total_in} 篇，{'待' if args.dry_run else ''}合订 {total_out} 篇。")
    if not args.dry_run:
        print("需要回退：合订前先 tar 一份 memory/，别省这一步。")


# ---------- find ----------

def cmd_find(args) -> None:
    root = Path(args.dir).resolve()
    cfg = load_cfg(root)

    # 纯日期走标准路径；带后缀的（2026-08-30-night 这类伴生条目）直接按节标题捞
    try:
        d = date.fromisoformat(args.day)
    except ValueError:
        d = None

    if d is not None:
        src, body = diary_text(root, cfg, d)
        if body:
            print(f"<!-- {src} -->\n{body}")
            return

    ddir = root / cfg["diary_dir"]
    for book in sorted(ddir.glob(f"{cfg['diary_prefix']}*.md")):
        lines = book.read_text(encoding="utf-8").split("\n")
        for i, ln in enumerate(lines):
            if ln.strip() == f"## {args.day}":
                end = len(lines)
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("## "):
                        end = j
                        break
                print(f"<!-- {book.name} · §{args.day} -->\n" +
                      "\n".join(lines[i:end]).strip())
                return
    die(f"{args.day} 没有记录")


# ---------- size ----------

def cmd_size(args) -> None:
    root = Path(args.dir).resolve()
    rows = []
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or p.name == "__pycache__":
            continue
        fs = [q for q in p.rglob("*") if q.is_file()] if p.is_dir() else [p]
        rows.append((p.name, sum(q.stat().st_size for q in fs), len(fs)))
    rows.sort(key=lambda r: -r[2])
    total = sum(r[2] for r in rows)
    print(f"\n{'目录/文件':<24}{'体积':>9}{'条目':>7}{'占比':>8}")
    for name, sz, n in rows:
        print(f"{name:<24}{human(sz):>9}{n:>7}{(n/total*100 if total else 0):>7.0f}%")
    print(f"{'合计':<24}{human(sum(r[1] for r in rows)):>9}{total:>7}100%\n")


# ---------- 入口 ----------

def main() -> None:
    ap = argparse.ArgumentParser(prog="selfkit", description="让 AI 记得自己是谁")
    ap.add_argument("--dir", default=".", help="人格根目录（默认当前目录）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="生成人格骨架")
    p.add_argument("--dir", default=".")
    p.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("boot", help="拼出这次会话要读的那一份")
    p.add_argument("--dir", default=".")
    p.add_argument("--out", help="写到文件而不是标准输出")
    p.add_argument("--quiet", action="store_true", help="只报字节数")
    p.add_argument("--no-diary", action="store_true", help="不附带今天和昨天的日记")
    p.set_defaults(func=cmd_boot)

    p = sub.add_parser("doctor", help="体检")
    p.add_argument("--dir", default=".")
    p.add_argument("--strict", action="store_true", help="有问题时以非零码退出")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("compact", help="日记按月合订")
    p.add_argument("--dir", default=".")
    p.add_argument("--month", help="只合订某个月，如 2026-08")
    p.add_argument("--dry-run", action="store_true", help="只看不做")
    p.set_defaults(func=cmd_compact)

    p = sub.add_parser("find", help="定位某天的日记原文")
    p.add_argument("day", help="YYYY-MM-DD")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("size", help="条目与体积报表")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_size)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
