#!/usr/bin/env node
/**
 * 工作区代码指纹（提交门禁共享组件）
 *
 * 对「代码范围」（见 SCOPE_*）内磁盘上的文件内容计算 sha256 指纹：
 *  - 供 tester / quality-engineer 检查通过后写入标记文件
 *  - 供 git-commit-gate 在提交前重新计算并比对（单一事实来源）
 *
 * 用法：node .claude/hooks/worktree-fingerprint.mjs [--dir <仓库根目录>]
 * 未指定 --dir 时，从当前目录向上寻找 .git 所在目录作为仓库根。
 * stdout 只输出指纹（hex），错误写 stderr 并以退出码 1 结束。
 *
 * 本项目（RAG 知识库问答系统）适配版：自「记账APP」项目迁移，代码范围由
 * hm-ledger（Tauri 前端 + Rust 后端）改为 backend/app + backend/tests（pytest）
 * + frontend/src（Vitest 用例与源码同目录）及清单内依赖/构建配置文件。
 */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// 代码 = 门禁范围（改动这些文件才需要门禁；纯文档不算）
const SCOPE_DIRS = [
  "backend/app",
  "backend/tests",
  "frontend/src",
];
const SCOPE_FILES = [
  "backend/requirements.txt",
  "frontend/package.json",
  "frontend/package-lock.json",
  "frontend/vite.config.ts",
  "frontend/tsconfig.json",
];

/** 判断仓库相对路径是否属于代码范围（门禁判定 + 指纹收集共用） */
export function isCodePath(rel) {
  const p = rel.replaceAll("\\", "/");
  for (const d of SCOPE_DIRS) {
    if (p === d || p.startsWith(d + "/")) return true;
  }
  return SCOPE_FILES.includes(p);
}

/** 收集代码范围内的全部相对路径（目录递归，含新增/未跟踪文件） */
function collectPaths(root) {
  const out = [];
  const walk = (absDir, relDir) => {
    let entries;
    try {
      entries = readdirSync(absDir);
    } catch {
      return; // 目录不存在则跳过
    }
    for (const name of entries.sort()) {
      const abs = join(absDir, name);
      const rel = relDir ? `${relDir}/${name}` : name;
      let st;
      try {
        st = statSync(abs);
      } catch {
        continue;
      }
      if (st.isDirectory()) walk(abs, rel);
      else if (st.isFile()) out.push(rel);
    }
  };
  for (const d of SCOPE_DIRS) {
    const abs = join(root, d);
    try {
      if (statSync(abs).isDirectory()) walk(abs, d);
    } catch {
      /* 目录不存在则跳过 */
    }
  }
  for (const f of SCOPE_FILES) {
    const abs = join(root, f);
    try {
      if (statSync(abs).isFile()) out.push(f);
    } catch {
      /* 文件不存在则跳过 */
    }
  }
  return out.sort();
}

/** 计算代码范围指纹（内容哈希；不含 HEAD，避免「检查后提交了别的」误拒） */
export function computeFingerprint(root) {
  const hash = createHash("sha256");
  for (const rel of collectPaths(root)) {
    let content;
    try {
      content = readFileSync(join(root, rel));
    } catch {
      continue; // 读取失败的文件不参与指纹
    }
    hash.update(rel.replaceAll("\\", "/"));
    hash.update("\0");
    hash.update(content);
  }
  return hash.digest("hex");
}

/** 从 cwd 向上找 .git，返回仓库根目录 */
export function findRepoRoot(startDir) {
  let dir = resolve(startDir);
  for (;;) {
    try {
      if (statSync(join(dir, ".git")).isDirectory() || statSync(join(dir, ".git")).isFile()) return dir;
    } catch {
      /* 继续向上 */
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function main() {
  const argv = process.argv.slice(2);
  let dir = process.cwd();
  const i = argv.indexOf("--dir");
  if (i !== -1 && argv[i + 1]) dir = argv[i + 1];
  const root = findRepoRoot(dir);
  if (!root) {
    process.stderr.write("worktree-fingerprint: 未找到 .git 仓库根目录\n");
    process.exit(1);
  }
  process.stdout.write(computeFingerprint(root));
}

// 允许被其它脚本 import（git-commit-gate.mjs）；直接执行时计算指纹
const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  try {
    main();
  } catch (err) {
    process.stderr.write(`worktree-fingerprint: ${err.message}\n`);
    process.exit(1);
  }
}
