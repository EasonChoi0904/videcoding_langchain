# RAG 知识库问答系统 — 项目说明与协作规范

## 一、项目概述

| 项目 | 说明 |
|---|---|
| 项目名 | 基于 LangChain 的企业级 RAG 知识库问答系统（毕业设计，电商商品 Q&A 场景） |
| 角色 | 管理员 admin/123456：知识库/文档管理、系统设置、统计与调试；普通用户：注册登录后问答（多会话、多语言） |
| 运行形态 | 纯单机双服务脚本运行（无 Docker/Redis）：后端 FastAPI :8000 + 前端 Vite :5173，双击 `start-all.bat` 启动 |

## 二、技术栈与目录结构

| 端 | 技术栈 | 代码位置 |
|---|---|---|
| 后端 | Python + FastAPI + SQLAlchemy（SQLite/FTS5 关键词检索）+ Qdrant（本地嵌入式，向量库）+ LangChain 1.x（LCEL 流式链） | [backend/app/](backend/app/)（api/ core/ models/ rag/ services/）、测试在 [backend/tests/](backend/tests/)（pytest） |
| 前端 | Vue 3 + TypeScript + Element Plus + Pinia + Vite 5 | [frontend/src/](frontend/src/)（api/ components/ stores/ views/）、测试同目录 `*.test.ts`（Vitest） |
| 大模型 | 阿里云百炼 OpenAI 兼容端点：qwen-plus（问答）/ text-embedding-v4（向量，批量上限 10）/ qwen3-rerank（重排） | 密钥在 `backend/.env` 的 `DASHSCOPE_API_KEY`（勿提交） |

核心链路：混合检索（稠密向量 + FTS 关键词 → RRF 融合 → rerank 重排 → 拒答阈值）→ 注入 prompt 流式生成，回答带引用溯源（citations，标注命中的知识库片段）。本地数据在 `backend/data/`（SQLite + Qdrant，勿提交）。

## 三、常用命令（dev 形态）

- 启动：`start-all.bat`，或让 Claude 用 `/run-app` 技能（双服务后台起，等价于双击）
- 测试：后端 `cd backend && .venv/Scripts/python -m pytest tests/ -q`；前端 `cd frontend && npm test`（完整流程走 `/unit-test` 技能或 @tester）
- 构建生产版：`/rebulid-app`（vue-tsc 类型检查 + vite build + 后端依赖核对）
- 检查类：`/comments-check`（注释质量）、`/security-audit`（安全审计）
- 交互式问答与检索验证：管理员在网页「检索调试台」页可单独验证检索召回效果

## 四、提交纪律与门禁（2026-09-06 自记账APP 项目迁移）

- 协作设施（2026-09-06 自记账APP 项目迁移后重整）：**技能为 user 全局统一版**——`/unit-test`、`/run-app`、`/rebulid-app`、`/git-save`、`/comments-check`、`/security-audit` 对两个项目通用，技能内按仓库结构自动识别技术栈分支（本项目 =「RAG 双服务 / Python pytest」；记账APP =「Tauri / Rust」）；**agents 为项目级**（@tester / @quality-engineer / @gitcommit-agent，各仓库自带同名副本）；**hooks** 项目内（`.claude/hooks/*.mjs` 门禁引擎 + `.githooks/` 原生 hook 注册脚本）
- **代码改动提交前必须先过两道门**：tester 全测试绿 + quality-engineer 无中危及以上问题，由 `@gitcommit-agent` 并行编排，通过后写入 `.quality-gates/*.pass.json`（含代码指纹）；**纯文档改动不受限**；紧急绕过：`git commit --no-verify`
- **项目尚未 git init**（当前状态）：门禁文件已全部就位但未生效。用户决定建仓后执行一次即可启用，之后克隆到新机器同样执行：

  ```
  git init -b main
  git config core.hooksPath .githooks
  ```

  未配置远程时只提交不推送（由 `/git-save` 技能按约定询问用户）
- 技术选型类决策延续本项目惯例：Claude 列候选方案 → 用户挑选 → 确认后才实施

## 五、账号与试用

管理员：admin / 123456（登录页不展示，仅文档记录）；普通用户：注册即可。演示数据：`backend/scripts/create_demo_data.py`（两个演示知识库，几十条商品问答分块）。
