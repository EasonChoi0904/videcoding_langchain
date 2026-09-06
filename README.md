# LangChain RAG 企业级电商知识库问答系统

基于 **LangChain** 框架开发的企业级 RAG(检索增强生成)知识库问答系统,面向电商平台售货场景:
管理员上传商品资料(PDF/Word/Excel/CSV/TXT/MD/HTML)构建知识库,普通用户通过浏览器向商品知识库提问,
回答**自带引用溯源**,支持**多会话、多语言对话**与**历史会话找回**。

## 功能一览

| 模块 | 说明 |
|---|---|
| 用户体系 | 注册 / 登录 / 修改密码;JWT 双令牌 + 刷新轮换;登录限流与失败锁定;角色 RBAC |
| 知识库管理(仅管理员) | 多知识库、多格式文档上传、解析任务进度、分块浏览/搜索/删除、覆盖重传、检索调试台 |
| 智能问答 | 混合检索 + 重排 + 拒答判定;SSE 流式输出;**引用溯源**(正文 [n] 上标 + 引用片段面板) |
| 会话能力 | 每个用户多会话;每会话独立语言(中文/英文/自动);历史会话持久化可随时找回 |
| 会话管理 | 游标分页加载历史、自动命名、改名/删除/搜索/导出(Markdown)、消息点赞点踩、停止/重新生成 |
| 系统管理 | 检索参数与提示词动态配置(即时生效)、统计看板(规模/趋势/耗时/反馈)、检索调试台 |

## 技术栈

- **后端**:Python 3.11+ · FastAPI · SQLAlchemy 2.0(async)· **LangChain 0.3/1.x(LCEL)**
- **AI 能力(阿里云百炼,一个 API Key 全包)**:
  - 对话:`qwen-plus`(OpenAI 兼容接口,可在 .env 切换)
  - 向量:`text-embedding-v4`(1024 维,批量 10 条/次)
  - 重排:`qwen3-rerank`(交叉编码精排)
- **向量库**:Qdrant 嵌入式本地模式(零独立进程,生产可无缝切服务版)
- **检索**:向量(dense)+ 关键词(SQLite FTS5 trigram + jieba,入库归一化)双路召回 → **RRF 融合** → 云端重排 → **阈值拒答防幻觉**
- **存储**:SQLite(WAL)+ FTS5;ORM 抽象层保留平滑迁移 PostgreSQL 的能力
- **前端**:Vue3 · Vite · TypeScript · Element Plus · Pinia · vue-i18n(中英 UI)
- **部署**:纯单机脚本(Windows `start.bat`),无 Docker/Redis 依赖

## 快速开始

### 0. 准备

1. 安装 [Python 3.11+](https://www.python.org/downloads/) 与 [Node.js 18+](https://nodejs.org/)
2. 注册[阿里云百炼](https://bailian.console.aliyun.com)获取 API Key(有免费额度)
3. 确认可用的模型名(控制台「模型广场」):对话 qwen-plus、向量 text-embedding-v4、重排 qwen3-rerank

### 1. 启动后端(端口 8000)

```bat
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          :: 填入 DASHSCOPE_API_KEY(可改成 .env)
start.bat                        :: 或 .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

验证:浏览器打开 http://localhost:8000/docs (Swagger 接口文档);默认管理员 **admin / 123456**(启动自动创建,请尽快修改)。

### 2. 启动前端(端口 5173)

```bat
cd frontend
npm install
npm run dev
```

浏览器访问 **http://localhost:5173** 即可开始使用。

### 3. (可选)一键生成演示数据

确保后端已启动,然后:

```bat
cd backend
.venv\Scripts\python.exe scripts\create_demo_data.py
```

生成两个演示知识库(手机数码 34 分块 + 大家电 30 分块),上传并等待解析完成后即可体验问答。

## 检索链路(一次问答的完整流程)

```
用户提问
  ├─ 语义缓存检查(仅会话首问;命中 → 直接回放,秒回)
  ├─ 双路召回
  │    ├─ 向量路:百炼 embedding → Qdrant 近邻 top-20(kb_id 可过滤)
  │    └─ 关键词路:jieba 拆词 → FTS5 trigram top-20
  ├─ RRF 融合 → top-10
  ├─ qwen3-rerank 交叉编码精排 → top-5
  ├─ 拒答判定:最高分 < 阈值(默认 0.45,管理端可调)→ 明确答复"未找到",不编造
  ├─ 引用先发:引用片段经 SSE citations 事件送达 → 前端引用面板立即展示
  ├─ LCEL 流式生成:正文标注 [1][2] 与引用片段一一对应
  └─ 完成落库(内容 + 引用 JSON 持久化,历史回看引用完整保留)
```

## 项目结构

```
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI 入口(lifespan:初始化/清理半截消息/启动 worker)
│  │  ├─ core/              # 配置(.env)/安全(JWT+bcrypt)/限流/RBAC
│  │  ├─ models/            # SQLAlchemy 数据模型(每张表带中文注释)
│  │  ├─ schemas/           # Pydantic 请求/响应
│  │  ├─ api/               # auth/kb/documents/chunks/debug/chat/conversations/settings/stats
│  │  ├─ rag/               # provider(百炼适配)/splitter(解析分块)/retriever(混合检索)
│  │  │                     # chain(LCEL 生成链)/cache(语义缓存)/history(长会话压缩)
│  │  └─ services/          # vector_store(Qdrant)/fts(FTS5)/ingestion(解析 worker)
│  ├─ scripts/create_demo_data.py
│  ├─ tests/                # pytest(34 用例:安全/分块/分词/融合/提示词)
│  ├─ data/                 # SQLite + Qdrant + 上传文件(自动创建)
│  └─ start.bat
└─ frontend/                # Vue3 + Element Plus 单页应用
```

## 性能与健壮性设计(论文素材)

1. **混合检索 + 两级精排**:双路召回 RRF 融合,兼顾语义与型号/专有名词精确命中
2. **引用过滤与拒答阈值**:弱相关片段不进引用面板;低于阈值明确拒答,防客服场景幻觉
3. **语义缓存**:同义首问命中直接回放(实测 2.5s → 0.3s),知识库变更自动失效
4. **流式体验**:SSE + 引用先于正文;周期落库快照,断线半截消息可"重新生成"
5. **长会话压缩**:窗口外历史后台 LLM 摘要化,上下文成本不随轮数膨胀
6. **并发与一致**:会话级互斥锁、全局生成信号量、SQLite WAL、按批提交进度可见
7. **安全**:bcrypt 盐哈希、JWT 双令牌 + jti 唯一、刷新轮换吊销、登录限流 + 账号锁定、
   文件类型白名单、参数白名单校验、Markdown 防 XSS
8. **可观测**:全接口 Swagger、启动能力探测、日志文件、统计看板(趋势/耗时/反馈)

## 常见问题

- **Q:对话报"未配置 API Key"?** A:检查 backend/.env 的 DASHSCOPE_API_KEY(或系统环境变量)。
- **Q:报"向量维度不一致"?** A:.env 的 VECTOR_SIZE 必须与 text-embedding-v4 输出一致(默认 1024);
  改动维度需删除 data/qdrant 与 data/app.db 重新入库。
- **Q:想换对话模型?** A:改 .env 的 CHAT_MODEL(qwen-turbo/max/flash 等,以百炼控制台开放为准),重启即可。
- **Q:换向量/重排模型?** A:改 .env 的 EMBEDDING_MODEL / RERANK_MODEL;向量模型变更后需重建集合重新入库。
- **Q:知识库在问答时答不上来?** A:用管理员「检索调试台」逐级查看召回/分数,动态调低/调高拒答阈值观察。
- **Q:部署到服务器?** A:后端 `uvicorn app.main:app --host 0.0.0.0`,前端 `npm run build` 后用任意静态服务器托管,
  由 Nginx 把 /api 反代到后端即可;如需 PostgreSQL,将 database_url 改为 pg 连接串(ORM 已适配)。

## 论文/答辩要点提示

- 系统架构图与数据库表中文注释已内嵌代码,可直接截图
- 检索调试台是"混合检索 + 重排"效果对比的最佳演示素材
- 统计看板与语义缓存命中日志可支撑性能对比数据(缓存命中前后耗时)
- 完整 SSE 协议、引用溯源、拒答防幻觉设计均可展开讲解

## 免责声明

- 项目为毕业设计/教学用途;内置演示数据为虚构商品信息,不代表真实商品。
- 请勿将真实 API Key 提交到公开仓库(.env 已在 .gitignore 中)。
