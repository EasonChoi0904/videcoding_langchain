#!/usr/bin/env node
/**
 * 提交门禁核心（原生 git hook 模式）
 *
 * 用法：
 *   node .claude/hooks/git-commit-gate.mjs git-pre    ← pre-commit hook：校验，拒绝时 stderr+exit 1
 *   node .claude/hooks/git-commit-gate.mjs git-post   ← post-commit hook：提交成功即清理标记
 *   node .claude/hooks/git-commit-gate.mjs pre        ← Claude Code PreToolUse（预留，当前环境未用）
 *   node .claude/hooks/git-commit-gate.mjs post       ← Claude Code PostToolUse（预留）
 *
 * 设计要点：
 *  - 质量检查由 tester/quality-engineer agent 完成并写入 .quality-gates/*.pass.json，
 *    本脚本只做「校验官」：验证标记存在 + 指纹匹配，通过才放行
 *  - 只拦「代码范围」改动（见 worktree-fingerprint.mjs 的 SCOPE_*）；纯文档提交放行
 *  - 标记指纹含提交瞬间的代码内容哈希；post-commit 成功后清理标记，
 *    使每次代码提交都必须重新走检查流程
 *  - 脚本必须绝对健壮：任何异常在 Claude 模式下走 exit 0；
 *    git 模式异常保守 exit 1（宁可拦一次也不放过，可通过 --no-verify 紧急绕过）
 */
import { execSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { findRepoRoot, computeFingerprint, isCodePath } from "./worktree-fingerprint.mjs";

const MARKER_FILES = ["tester.pass.json", "quality.pass.json"];
const DENY_MISSING =
  "提交被门禁拦截：尚未通过单元测试、质量检查，不能存档。请先运行 @gitcommit-agent 完成检查后再提交。";
const DENY_STALE =
  "提交被门禁拦截：代码自上次检查后有改动，旧标记已失效。请重新运行 @gitcommit-agent 后再提交。";

function readStdin() {
  try {
    const raw = readFileSync(0, "utf8");
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

/** 是否是 git commit 类命令（含 -m/--amend/-a 等变体） */
function isGitCommit(command) {
  return /(^|[;&|]\s*)git(\s+(-[a-zA-Z]+\s*)*)?\s+commit(\s|$)/.test(command);
}

function git(args, repoRoot) {
  return execSync(`git ${args}`, { cwd: repoRoot, encoding: "utf8" }).trim();
}

function markersDir(repoRoot) {
  return join(repoRoot, ".quality-gates");
}

function readMarkers(repoRoot) {
  const dir = markersDir(repoRoot);
  const found = {};
  for (const f of MARKER_FILES) {
    const p = join(dir, f);
    if (!existsSync(p)) continue;
    try {
      found[f] = JSON.parse(readFileSync(p, "utf8"));
    } catch {
      found[f] = null; // 标记损坏视为缺失
    }
  }
  return found;
}

/** 暂存区是否含代码范围改动 */
function stagedHasCode(repoRoot) {
  let names = [];
  try {
    names = git("diff --cached --name-only", repoRoot).split("\n").filter(Boolean);
  } catch {
    return true; // git 查询失败时保守视为有代码改动
  }
  return names.some((n) => isCodePath(n));
}

/** 门禁校验：返回 { ok: true } 或 { ok: false, reason } */
function gateCheck(repoRoot) {
  if (!stagedHasCode(repoRoot)) return { ok: true }; // 纯文档/非代码提交 → 放行
  const markers = readMarkers(repoRoot);
  const missing = MARKER_FILES.filter((f) => !markers[f] || markers[f].verdict !== "pass");
  if (missing.length) return { ok: false, reason: DENY_MISSING };
  let current;
  try {
    current = computeFingerprint(repoRoot);
  } catch {
    return { ok: true }; // 指纹计算异常时不阻塞（人工复核通道始终可用：--no-verify）
  }
  const stale = MARKER_FILES.some((f) => markers[f].fingerprint !== current);
  if (stale) return { ok: false, reason: DENY_STALE };
  return { ok: true };
}

/** 清理标记（提交成功后的唯一清理点） */
function clearMarkers(repoRoot) {
  for (const f of MARKER_FILES) {
    try {
      rmSync(join(markersDir(repoRoot), f), { force: true });
    } catch {
      /* 忽略清理失败 */
    }
  }
}

// ---------- 模式分发 ----------

function main() {
  const mode = process.argv[2] ?? "pre";

  // 原生 git hook 模式：git 保证 hook 的工作目录是仓库根
  if (mode === "git-pre") {
    const result = gateCheck(process.cwd());
    if (!result.ok) {
      process.stderr.write(`\n✗ ${result.reason}\n`);
      process.exit(1); // 非零退出 = 拒绝本次提交
    }
    process.exit(0);
  }
  if (mode === "git-post") {
    clearMarkers(process.cwd()); // post-commit 只在提交成功后执行
    process.exit(0);
  }

  // Claude Code hook 模式（预留）：读 stdin 事件 JSON
  const event = readStdin();
  const command = event.tool_input?.command ?? event.tool_response?.command ?? "";
  if (!isGitCommit(command)) return; // 非 git commit → 不做决定
  const cwd = event.cwd || process.cwd();
  const repoRoot = findRepoRoot(join(cwd)) ?? cwd;

  if (mode === "post") {
    if (event.exit_code === 0 || event.tool_response?.exit_code === 0) clearMarkers(repoRoot);
    return;
  }
  const result = gateCheck(repoRoot);
  if (!result.ok) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: result.reason,
        },
      })
    );
  }
}

try {
  main();
} catch (err) {
  // Claude 模式绝不崩溃；git 模式保守拒绝（可用 --no-verify 紧急绕过）
  const isGitMode = process.argv[2] === "git-pre" || process.argv[2] === "git-post";
  if (isGitMode) {
    process.stderr.write(`\n✗ 门禁脚本异常，已阻止提交（如需绕过：git commit --no-verify）\n${err?.message ?? err}\n`);
    process.exit(1);
  }
  process.stderr.write(`git-commit-gate: ${err?.message ?? err}\n`);
  process.exit(0);
}
