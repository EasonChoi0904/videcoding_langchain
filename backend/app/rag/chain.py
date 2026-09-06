"""问答生成链:LangChain(LCEL)编排生成阶段。

设计:
- 系统提示词 = 角色设定(管理端可覆盖)+ 语言指令 + 引用编号规范
- 用户消息 = 编号参考资料(仅这些片段可被 [n] 引用)+ 早期摘要 + 近轮历史 + 当前问题
- 流式生成:prompt | llm 的 LCEL 链,astream 逐个产出内容增量

引用协议(引用溯源三要素之一,与前端/检索层配合):
- 资料以 [1]..[N] 编号列出,提示词强约束模型只准引用这些编号
- 检索片段先于正文经 SSE citations 事件送达前端,正文 [n] 与之对应
"""
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.core.settings import get_settings
from app.rag.provider import make_chat_model

logger = logging.getLogger(__name__)

# 默认系统提示词(管理端可在 settings.system_prompt 覆盖)
DEFAULT_SYSTEM_PROMPT = (
    "你是一位专业、耐心的电商平台智能客服助手,面向消费者解答商品选购与使用问题。"
    "你的全部知识来自给定的商品知识库资料,回答问题必须严格依据资料内容。"
)

# 语言指令模板(按会话语言注入)
LANGUAGE_INSTRUCTIONS = {
    "zh": (
        "回答语言规则(必须遵守):无论用户用什么语言提问(包括英文提问),"
        "你都必须使用简体中文作答;商品名称/品牌/型号等专有名词可保留原文。"
    ),
    "en": (
        "Answer language rule (must follow): regardless of the language the user "
        "asks in, you must answer in fluent English. Keep product/brand/model names as-is."
    ),
    "auto": "请使用与用户提问一致的语言回答(中文问中文答,英文问英文答)。",
}

# 追加在用户消息末尾的回复语言要求(模型对最近的指令服从性最高,双保险)
LANGUAGE_HINTS = {
    "zh": "【回复要求】请使用简体中文回答(英文提问也必须用中文作答)。",
    "en": "【Reply requirement】Please answer in English.",
}

# 拒答文案(检索低于拒答阈值时的兜底话术,防幻觉)
REFUSAL_TEXTS = {
    "zh": (
        "抱歉,知识库中暂时没有找到与您问题相关的商品资料,我无法给出可靠的回答。\n\n"
        "您可以尝试:① 换一种说法描述商品或问题;② 提供更具体的商品名称/型号;"
        "③ 联系人工客服咨询。"
    ),
    "en": (
        "Sorry, I could not find related product information in the knowledge base, "
        "so I cannot give a reliable answer. Please try rephrasing your question, "
        "or contact our customer service for help."
    ),
}

# 对话历史注入的最大字符数(超出部分截断,更早内容由后台压缩任务接管)
_HISTORY_CHAR_CAP = 4000


def detect_language(question: str) -> str:
    """auto 语言模式探测:按中文字符占比判定。"""
    cjk = len(re.findall(r"[一-龥]", question))
    if cjk >= 2:
        return "zh"
    return "zh" if cjk > 0 and cjk / max(len(question), 1) > 0.2 else "en"


def build_system_content(language: str, system_prompt_override: str | None = None) -> str:
    """系统提示词 = 角色设定 + 语言指令 + 引用编号规范。"""
    lang = "zh" if language == "auto" else language
    base = (system_prompt_override or DEFAULT_SYSTEM_PROMPT).strip()
    parts = [
        base,
        LANGUAGE_INSTRUCTIONS.get(lang, LANGUAGE_INSTRUCTIONS["auto"]),
        (
            "参考资料格式:每条资料以 [n] 开头。回答正文中如引用了某条资料的信息,"
            "请在该信息后标注 [n];同一信息可标注多个编号如 [1][3]。\n"
            "引用规范:① 只能引用资料中实际存在的内容,严禁编造;"
            "② 若资料相互矛盾,如实指出并引用原文;"
            "③ 价格/规格/保修等参数必须与资料一致并标注 [n] 便于用户核对;"
            "④ 不要输出资料之外的信息,不确定时建议用户联系人工客服;"
            "⑤ 若完全没有可用资料,请礼貌说明无法回答。"
        ),
    ]
    return "\n\n".join(parts)


def build_source_block(sources: list[dict]) -> str:
    """引用片段 → 编号资料块(送入用户消息)。

    注意:sources 的 location 已是完整描述(如"第 3 页"/"表格第 2 行"),
    这里直接以括号括起,不再拼接前缀。
    """
    lines = []
    for i, src in enumerate(sources, start=1):
        text = (src.get("text") or "").strip().replace("\n", " ")
        location = f"({src['location']})" if src.get("location") else ""
        lines.append(f"[{i}] 来源:《{src.get('doc_name', '')}》{location}\n{text}")
    return "\n\n".join(lines)


def format_history(history: list[dict]) -> list[str]:
    """历史消息 → 文本行,超长时截断较早内容(防上下文膨胀)。"""
    lines: list[str] = []
    total = 0
    for item in reversed(history):  # 从最近开始拼,超限即停,再整体反转回时间序
        role = "用户" if item["role"] == "user" else "客服"
        line = f"{role}: {item['content']}"
        total += len(line)
        if total > _HISTORY_CHAR_CAP:
            break
        lines.append(line)
    return list(reversed(lines))


def build_user_content(
    question: str,
    source_block: str,
    summary_text: str | None,
    history_lines: list[str],
    language: str | None = None,
) -> str:
    """用户消息 = 编号资料 + 早期摘要 + 近轮历史 + 当前问题 + 回复语言要求。"""
    parts: list[str] = []
    if source_block:
        parts.append(f"【参考资料】\n{source_block}")
    if summary_text:
        parts.append(f"【更早对话摘要】\n{summary_text}")
    if history_lines:
        parts.append("【对话历史】\n" + "\n".join(history_lines))
    parts.append(f"【当前问题】\n{question}")
    # 语言要求放在最末:模型对"最后一条指令"的服从性最强(修正英文提问
    # 会"带跑"回答语言的问题;auto 模式不追加,保持跟随提问语言)
    hint = LANGUAGE_HINTS.get(language or "")
    if hint:
        parts.append(hint)
    return "\n\n".join(parts)


async def stream_answer(system_content: str, user_content: str, temperature: float = 0.3):
    """LCEL 流式生成:prompt | llm 链,逐增量产出正文。"""
    llm = make_chat_model(streaming=True, temperature=temperature)
    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), ("human", "{user}")]
    )
    chain = prompt | llm
    async for chunk in chain.astream({"system": system_content, "user": user_content}):
        if chunk.content:
            yield chunk.content
