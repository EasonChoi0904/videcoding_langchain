"""应用配置模块。

集中管理所有可调参数:路径、密钥、JWT 策略、阿里云百炼模型配置、RAG 检索参数等。
所有配置均可通过 backend/.env 文件覆盖(见 .env.example),避免把密钥写死在代码里。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录的绝对路径(本文件位于 backend/app/core/ 下)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """全局配置,字段名与 .env 中的键一一对应(忽略大小写)。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ==================== 基础信息 ====================
    app_name: str = "LangChain RAG 企业级知识库问答系统"
    debug: bool = True
    api_prefix: str = "/api"

    # ==================== 安全 / JWT ====================
    # 生产环境务必在 .env 中改为随机长字符串
    secret_key: str = "dev-only-secret-key-please-change-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30   # 访问令牌有效期(短,泄露风险小)
    refresh_token_expire_days: int = 7      # 刷新令牌有效期(长,支持"找回"登录态)
    # 登录失败锁定:连续失败超过阈值后锁定该账号一段时间(防暴力破解)
    login_max_failures: int = 5
    login_lock_minutes: int = 10

    # ==================== 本地存储 ====================
    data_dir: Path = BASE_DIR / "data"      # 业务库 / 向量库 / 上传文件都放这里
    upload_dir: Path = BASE_DIR / "data" / "uploads"   # 上传原文件落盘目录(uuid 命名)

    @property
    def database_url(self) -> str:
        """SQLite 异步连接串(SQLAlchemy 抽象层,论文中可说明平滑迁移 PostgreSQL)。"""
        return f"sqlite+aiosqlite:///{self.data_dir / 'app.db'}"

    @property
    def qdrant_path(self) -> Path:
        """Qdrant 嵌入式本地模式的数据目录(纯 Python 进程内运行,无独立服务)。"""
        return self.data_dir / "qdrant"

    # ==================== 向量库(Qdrant)====================
    vector_collection: str = "product_chunks"   # 商品分块向量集合
    cache_collection: str = "question_cache"    # 语义缓存(问题向量)集合
    vector_size: int = 1024                     # text-embedding-v4 输出维度(必须与建集合一致)
    qdrant_distance: str = "Cosine"

    # ==================== 阿里云百炼 ====================
    # 用户已有百炼 API Key,对话/向量/重排全部走云端,本机无需任何大模型
    dashscope_api_key: str = ""                 # 必填:在百炼控制台获取
    # 对话走 OpenAI 兼容接口(langchain-openai ChatOpenAI 直接对接)
    chat_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chat_model: str = "qwen-plus"               # 质量/成本均衡档;可换 qwen-turbo/qwen-max/qwen-flash
    chat_timeout_seconds: int = 120

    # 向量:auto=启动时探测 compatible 接口是否可用,失败自动切 native 原生接口
    embedding_api_mode: str = "auto"            # auto | compatible | native
    embedding_model: str = "text-embedding-v4"
    embedding_batch_size: int = 10              # 每次批量嵌入条数(text-embedding-v4 官方上限 10)
    embedding_compatible_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_native_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    )

    # 重排:百炼原生 rerank 接口
    rerank_model: str = "qwen3-rerank"
    rerank_native_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )

    # ==================== RAG 检索参数(管理端可在 settings 表动态覆盖)====================
    # 注意:以下为"默认值",运行时优先读取 DB settings 表中的同名配置
    hybrid_each_top_k: int = 20     # 双路(向量/关键词)各召回条数
    rrf_k: int = 60                 # RRF 融合常数(论文标准取 60)
    rerank_top_n: int = 5           # 重排后保留条数(=引用片段上限)
    rerank_threshold: float = 0.45  # 重排分数低于该值 → 拒答(防幻觉;实测相关~0.9,无关~0.35)
    chunk_size: int = 500           # 文本分块目标长度(字符)
    chunk_overlap: int = 50         # 分块重叠长度,保上下文连续性

    # ==================== 语义缓存 ====================
    cache_enabled: bool = True
    cache_sim_threshold: float = 0.96   # 问题向量余弦相似度超过该值视为同一问题
    cache_ttl_seconds: int = 3600       # 缓存有效期

    # ==================== 限流(防滥用)====================
    rate_login_per_minute: int = 5      # 登录接口:同 IP+用户名 每分钟次数
    rate_ask_per_minute: int = 20       # 问答接口:每用户每分钟次数
    rate_register_per_hour: int = 10    # 注册接口:同 IP 每小时次数

    # ==================== 上传限制 ====================
    max_file_size_mb: int = 50
    allowed_extensions: tuple = (
        ".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".html", ".htm"
    )

    # ==================== 会话窗口 ====================
    history_recent_rounds: int = 10     # 进入提示词的最近轮数(每轮一问一答)
    history_compress_threshold_tokens: int = 4000  # 估算超过该量触发异步压缩


@lru_cache
def get_settings() -> Settings:
    """进程级单例(带缓存),所有模块共享同一份配置。"""
    return Settings()
