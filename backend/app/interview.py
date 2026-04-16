import json
from datetime import datetime
from typing import List, Optional, Dict, Callable, Any
from pydantic import BaseModel
from .code_analyzer import analyze_codebase, CodeAnalysis
from .deps import get_llm_instance
from .storage import get_filtered_knowledge_items, search_similar_knowledge_items
from langchain_core.messages import HumanMessage, SystemMessage


class InterviewQuestion(BaseModel):
    """面试问题模型"""
    question: str
    answer_hint: str
    difficulty: str  # easy, medium, hard
    category: str  # code_understanding, optimization, design, architecture
    reference_code: Optional[str] = None


class InterviewPlanStep(BaseModel):
    name: str
    description: str
    status: str = "pending"


class InterviewToolStatus(BaseModel):
    tool: str
    available: bool
    detail: str


class InterviewMessage(BaseModel):
    role: str
    content: str
    created_at: str


class SimilarKnowledgeItem(BaseModel):
    id: int
    question: str
    answer: str
    tags: List[str] = []
    category: Optional[str] = None
    created_at: Optional[str] = None
    similarity: Optional[float] = None


class InterviewSession:
    """面试会话模型"""
    def __init__(
        self,
        session_id: str,
        code_url: Optional[str] = None,
        analysis: Optional[CodeAnalysis] = None,
        questions: List[InterviewQuestion] = None
    ):
        self.session_id = session_id
        self.code_url = code_url
        self.analysis = analysis
        self.questions = questions or []
        self.created_at = datetime.now()
        self.status = "initialized"
        self.plan: List[InterviewPlanStep] = []
        self.tool_status: List[InterviewToolStatus] = []
        self.similar_questions: List[SimilarKnowledgeItem] = []
        self.messages: List[InterviewMessage] = []
        self.current_question_index = 0

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "code_url": self.code_url,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "questions": [q.model_dump() for q in self.questions],
            "plan": [step.model_dump() for step in self.plan],
            "tool_status": [tool.model_dump() for tool in self.tool_status],
            "similar_questions": [item.model_dump() for item in self.similar_questions],
            "messages": [message.model_dump() for message in self.messages],
            "current_question_index": self.current_question_index,
            "created_at": self.created_at.isoformat(),
            "status": self.status
        }


# 全局面试会话缓存
interview_sessions: Dict[str, InterviewSession] = {}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _build_interview_plan() -> List[InterviewPlanStep]:
    return [
        InterviewPlanStep(name="analyze_repo", description="分析代码仓库的结构、技术栈和关键模块", status="completed"),
        InterviewPlanStep(name="search_similar_questions", description="检索知识库中的相似问题和答案", status="completed"),
        InterviewPlanStep(name="ask_candidate", description="向用户逐轮提问并追问关键细节", status="in_progress"),
        InterviewPlanStep(name="evaluate_answers", description="根据回答质量给出反馈和改进建议", status="pending"),
    ]


def _build_tool_status() -> List[InterviewToolStatus]:
    return [
        InterviewToolStatus(tool="knowledge_similarity_search", available=True, detail="已接入本地知识库相似问题检索"),
        InterviewToolStatus(tool="web_search", available=False, detail="当前仓库未配置网络搜索 provider"),
        InterviewToolStatus(tool="headless_claude", available=False, detail="当前仓库未配置 Claude 无头调用入口"),
    ]


def _format_similar_questions(similar_questions: List[SimilarKnowledgeItem]) -> str:
    if not similar_questions:
        return "暂无相似问题。"

    lines = []
    for index, item in enumerate(similar_questions[:5], start=1):
        similarity = ""
        if item.similarity is not None:
            similarity = f"（相似度 {item.similarity:.2f}）"
        lines.append(f"{index}. {item.question}{similarity}")
        lines.append(f"   答案摘要: {item.answer[:180]}...")
    return "\n".join(lines)


def _format_questions(questions: List[InterviewQuestion]) -> str:
    if not questions:
        return "暂无候选问题。"
    return "\n".join(
        f"{index + 1}. [{question.category}] {question.question}"
        for index, question in enumerate(questions)
    )


def _append_session_message(session: "InterviewSession", role: str, content: str):
    session.messages.append(
        InterviewMessage(role=role, content=content, created_at=_now_iso())
    )


async def build_interview_kickoff(
    session: "InterviewSession",
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    """
    Build the initial interview kickoff message after analysis is complete.
    """
    analysis = session.analysis
    if analysis is None:
        return "代码分析尚未完成，暂时无法开始面试。"

    query_parts = [
        analysis.project_name,
        analysis.summary,
        " ".join(module for module in analysis.key_modules[:5]),
    ]
    query = "\n".join(part for part in query_parts if part)
    similar_items = await search_similar_knowledge_items(query, category=category, tags=tags, limit=5)
    session.similar_questions = [SimilarKnowledgeItem(**item) for item in similar_items]
    session.plan = _build_interview_plan()
    session.tool_status = _build_tool_status()
    session.current_question_index = 0
    session.status = "interviewing"

    first_question = session.questions[0].question if session.questions else "请先用 2 分钟介绍一下这个项目。"
    kickoff_message = (
        f"我会按这个顺序进行面试：先基于代码仓库做项目理解，再参考知识库中的相似问题，最后逐轮提问并根据你的回答继续追问。\n\n"
        f"项目：{analysis.project_name}\n"
        f"语言：{analysis.language}\n"
        f"核心技术栈：{', '.join(analysis.tech_stack) if analysis.tech_stack else '未知'}\n\n"
        f"知识库相似问题：\n{_format_similar_questions(session.similar_questions)}\n\n"
        f"第一题：{first_question}"
    )
    _append_session_message(session, "assistant", kickoff_message)
    return kickoff_message


async def generate_interview_questions(
    analysis: CodeAnalysis,
    difficulty: str = "medium",
    count: int = 10,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> List[InterviewQuestion]:
    """
    基于代码分析结果生成面试问题

    Args:
        analysis: 代码分析结果
        difficulty: 难度等级 (easy/medium/hard)
        count: 问题数量
        progress_callback: 进度回调函数

    Returns:
        list: 面试问题列表
    """
    if progress_callback:
        progress_callback(10, "准备生成面试问题")

    llm = await get_llm_instance()

    # 构建提示词
    difficulty_descriptions = {
        "easy": "基础问题，适合初级开发者",
        "medium": "中等难度问题，适合有经验的开发者",
        "hard": "高难度问题，适合高级开发者或架构师"
    }

    system_prompt = f"""你是一个专业的技术面试官，擅长基于实际代码生成面试问题。

请根据提供的代码分析结果，生成 {count} 个 {difficulty} 级别的面试问题。

问题类型要求多样化，包括：
1. 代码理解类 - 询问代码的功能、逻辑、意图
2. 优化改进类 - 询问如何优化性能、代码质量
3. 场景扩展类 - 询问如何添加新功能或处理新需求
4. 技术选型类 - 询问为何使用特定技术或架构
5. 架构设计类 - 询问整体架构设计原则

难度说明: {difficulty_descriptions.get(difficulty, "中等难度")}

请以 JSON 数组格式返回问题列表，每个问题包含：
{{
  "question": "面试问题文本",
  "answer_hint": "答案要点或提示（100-200字）",
  "category": "问题类型（code_understanding/optimization/design/architecture/extension）",
  "reference_code": "相关的代码片段（如果有）"
}}"""

    # 构建代码摘要
    code_summary = f"""
项目名称: {analysis.project_name}
编程语言: {analysis.language}

项目摘要:
{analysis.summary}

核心技术栈:
{', '.join(analysis.tech_stack) if analysis.tech_stack else '未知'}

关键模块:
{', '.join(analysis.key_modules) if analysis.key_modules else '未知'}

使用的设计模式:
{', '.join(analysis.design_patterns) if analysis.design_patterns else '无'}

关键代码文件预览:
"""
    for file_info in analysis.key_files[:3]:  # 只包含前3个文件
        code_summary += f"\n--- {file_info['filename']} ---\n"
        code_summary += file_info['content'][:500] + "...\n"

    if progress_callback:
        progress_callback(30, "使用 LLM 生成面试问题")

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"请基于以下代码分析生成面试问题：\n\n{code_summary}")
        ])

        content = response.content.strip()

        if progress_callback:
            progress_callback(70, "解析生成的问题")

        # 尝试提取 JSON 数组
        import re
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            json_content = json_match.group()
            try:
                questions_data = json.loads(json_content)

                questions = []
                for q_data in questions_data[:count]:  # 限制问题数量
                    question = InterviewQuestion(
                        question=q_data.get("question", ""),
                        answer_hint=q_data.get("answer_hint", ""),
                        difficulty=difficulty,
                        category=q_data.get("category", "code_understanding"),
                        reference_code=q_data.get("reference_code")
                    )
                    questions.append(question)

                if progress_callback:
                    progress_callback(100, "面试问题生成完成")

                return questions

            except json.JSONDecodeError as e:
                print(f"JSON 解析失败: {str(e)}")

        # 如果 JSON 解析失败，返回默认问题
        fallback_questions = [
            InterviewQuestion(
                question=f"请解释 {analysis.project_name} 项目的主要功能和业务逻辑",
                answer_hint="需要分析项目的核心业务逻辑和功能模块",
                difficulty=difficulty,
                category="code_understanding"
            )
        ]

        if progress_callback:
            progress_callback(100, "使用默认问题")

        return fallback_questions

    except Exception as e:
        print(f"生成面试问题失败: {str(e)}")

        # 返回默认问题
        return [
            InterviewQuestion(
                question=f"请解释 {analysis.project_name} 项目的主要功能和业务逻辑",
                answer_hint="需要分析项目的核心业务逻辑和功能模块",
                difficulty=difficulty,
                category="code_understanding"
            )
        ]


async def answer_interview_question(
    question: str,
    session_id: str,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> str:
    """
    回答面试问题，结合代码分析和知识库

    Args:
        question: 面试问题
        session_id: 面试会话 ID
        category: 知识库分类过滤
        tags: 知识库标签过滤

    Returns:
        str: 答案
    """
    # 获取面试会话
    if session_id not in interview_sessions:
        return "面试会话不存在"

    session = interview_sessions[session_id]
    analysis = session.analysis

    if not analysis:
        return "代码分析结果不存在"

    candidate_answer = question.strip()
    _append_session_message(session, "user", candidate_answer)

    kb_items = await get_filtered_knowledge_items(category=category, tags=tags)
    if not session.similar_questions:
        query = f"{analysis.project_name}\n{analysis.summary}\n{candidate_answer}"
        similar_items = await search_similar_knowledge_items(query, category=category, tags=tags, limit=5)
        session.similar_questions = [SimilarKnowledgeItem(**item) for item in similar_items]

    llm = await get_llm_instance()
    current_question = (
        session.questions[session.current_question_index].question
        if session.current_question_index < len(session.questions)
        else "请总结这个项目最值得优化的地方。"
    )
    remaining_questions = session.questions[session.current_question_index + 1 : session.current_question_index + 4]

    code_context = f"""
项目名称: {analysis.project_name}
编程语言: {analysis.language}
项目摘要:
{analysis.summary}

核心技术栈:
{', '.join(analysis.tech_stack) if analysis.tech_stack else '未知'}

关键模块:
{', '.join(analysis.key_modules) if analysis.key_modules else '未知'}

候选问题:
{_format_questions(session.questions)}

知识库相似问题:
{_format_similar_questions(session.similar_questions)}
"""
    for file_info in analysis.key_files[:2]:
        code_context += f"\n--- {file_info['filename']} ---\n{file_info['content'][:800]}...\n"

    history = "\n".join(f"{message.role}: {message.content}" for message in session.messages[-6:])
    kb_context = "\n".join(f"- {item['question']}: {item['answer'][:160]}..." for item in kb_items[:3]) or "无"
    next_question_hint = (
        remaining_questions[0].question
        if remaining_questions
        else "如果没有后续题目，请收束并给出总结反馈。"
    )

    system_prompt = """你是一个技术面试官 agent，而不是普通问答助手。

你的任务顺序固定：
1. 判断用户刚才的内容是“候选人回答”，而不是向你提问。
2. 对这段回答做简短评价：指出答得好的点、缺失的点、和代码仓库不一致的点。
3. 参考代码分析和知识库相似问题，给出 1-2 个追问点。
4. 最后只抛出一个下一题或下一轮追问。

约束：
- 你必须像面试官一样推进流程，而不是直接把标准答案全讲完。
- 输出要具体，必须和仓库代码、技术栈、模块相联系。
- 如果用户答得明显不对，要直接指出。
- 如果已经到最后一题，给出面试总结，并说明建议补强的方向。"""

    prompt = f"""当前题目：
{current_question}

候选人刚才的回答：
{candidate_answer}

最近对话：
{history}

代码与知识上下文：
{code_context}

知识库参考：
{kb_context}

建议下一题：
{next_question_hint}
"""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])
        content = response.content
        session.current_question_index = min(session.current_question_index + 1, max(len(session.questions) - 1, 0))
        if session.plan:
            session.plan[-1].status = "in_progress" if session.current_question_index < len(session.questions) - 1 else "completed"
        if session.current_question_index >= len(session.questions) - 1:
            session.status = "completed"
        _append_session_message(session, "assistant", content)
        return content
    except Exception as e:
        error_content = f"生成面试反馈失败: {str(e)}"
        _append_session_message(session, "assistant", error_content)
        return error_content


async def stream_answer_interview_question(
    question: str,
    session_id: str,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None
):
    """
    流式回答面试问题，结合代码分析和知识库

    Args:
        question: 面试问题
        session_id: 面试会话 ID
        category: 知识库分类过滤
        tags: 知识库标签过滤

    Yields:
        str: 流式答案
    """
    # 获取面试会话
    if session_id not in interview_sessions:
        yield f"data: {json.dumps({'content': '面试会话不存在'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    session = interview_sessions[session_id]
    analysis = session.analysis

    if not analysis:
        yield f"data: {json.dumps({'content': '代码分析结果不存在'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    user_answer = question.strip()
    _append_session_message(session, "user", user_answer)

    kb_items = await get_filtered_knowledge_items(category=category, tags=tags)
    if not session.similar_questions:
        query = f"{analysis.project_name}\n{analysis.summary}\n{user_answer}"
        similar_items = await search_similar_knowledge_items(query, category=category, tags=tags, limit=5)
        session.similar_questions = [SimilarKnowledgeItem(**item) for item in similar_items]

    current_question = (
        session.questions[session.current_question_index].question
        if session.current_question_index < len(session.questions)
        else "请总结这个项目最值得优化的地方。"
    )
    remaining_questions = session.questions[session.current_question_index + 1 : session.current_question_index + 4]
    history = "\n".join(f"{message.role}: {message.content}" for message in session.messages[-6:])
    kb_context = "\n".join(f"- {item['question']}: {item['answer'][:160]}..." for item in kb_items[:3]) or "无"

    code_context = f"""
项目名称: {analysis.project_name}
编程语言: {analysis.language}
项目摘要:
{analysis.summary}

核心技术栈:
{', '.join(analysis.tech_stack) if analysis.tech_stack else '未知'}

关键模块:
{', '.join(analysis.key_modules) if analysis.key_modules else '未知'}

候选问题:
{_format_questions(session.questions)}

知识库相似问题:
{_format_similar_questions(session.similar_questions)}
"""
    for file_info in analysis.key_files[:2]:
        code_context += f"\n--- {file_info['filename']} ---\n{file_info['content'][:800]}...\n"

    next_question_hint = (
        remaining_questions[0].question
        if remaining_questions
        else "如果没有后续题目，请收束并给出总结反馈。"
    )

    system_prompt = """你是一个技术面试官 agent，而不是普通问答助手。

你要根据候选人的回答给出面试式反馈，并推进下一轮问题。

输出结构：
1. 简短评价候选人回答
2. 指出缺失点或可追问点
3. 最后提出一个下一题或追问

约束：
- 基于实际代码仓库上下文，不要空泛。
- 不要直接把完整标准答案一次性讲完。
- 如果候选人回答与代码仓库不一致，要直接指出。
- 如果面试结束，给总结和补强建议。"""

    prompt = f"""当前题目：
{current_question}

候选人刚才的回答：
{user_answer}

最近对话：
{history}

代码与知识上下文：
{code_context}

知识库参考：
{kb_context}

建议下一题：
{next_question_hint}
"""

    assistant_chunks: List[str] = []
    try:
        llm = await get_llm_instance()
        async for chunk in llm.astream([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]):
            if chunk.content:
                assistant_chunks.append(chunk.content)
                yield f"data: {json.dumps({'content': chunk.content})}\n\n"

        assistant_content = "".join(assistant_chunks)
        _append_session_message(session, "assistant", assistant_content)
        session.current_question_index = min(session.current_question_index + 1, max(len(session.questions) - 1, 0))
        if session.plan:
            session.plan[-1].status = "in_progress" if session.current_question_index < len(session.questions) - 1 else "completed"
        if session.current_question_index >= len(session.questions) - 1:
            session.status = "completed"
        yield "data: [DONE]\n\n"

    except Exception as e:
        error_content = f"生成面试反馈失败: {str(e)}"
        _append_session_message(session, "assistant", error_content)
        yield f"data: {json.dumps({'content': error_content})}\n\n"
        yield "data: [DONE]\n\n"


def create_interview_session(
    session_id: str,
    code_url: Optional[str] = None
) -> InterviewSession:
    """
    创建面试会话

    Args:
        session_id: 会话 ID
        code_url: 代码 URL

    Returns:
        InterviewSession: 面试会话对象
    """
    session = InterviewSession(
        session_id=session_id,
        code_url=code_url
    )
    interview_sessions[session_id] = session
    return session


def get_interview_session(session_id: str) -> Optional[InterviewSession]:
    """
    获取面试会话

    Args:
        session_id: 会话 ID

    Returns:
        InterviewSession: 面试会话对象，如果不存在则返回 None
    """
    return interview_sessions.get(session_id)


def update_interview_session(
    session_id: str,
    analysis: CodeAnalysis,
    questions: List[InterviewQuestion]
) -> bool:
    """
    更新面试会话的分析结果和问题

    Args:
        session_id: 会话 ID
        analysis: 代码分析结果
        questions: 面试问题列表

    Returns:
        bool: 更新是否成功
    """
    if session_id not in interview_sessions:
        return False

    session = interview_sessions[session_id]
    session.analysis = analysis
    session.questions = questions
    session.status = "completed"
    session.plan = _build_interview_plan()
    session.tool_status = _build_tool_status()
    session.messages = []
    session.current_question_index = 0

    return True


def delete_interview_session(session_id: str) -> bool:
    """
    删除面试会话

    Args:
        session_id: 会话 ID

    Returns:
        bool: 删除是否成功
    """
    if session_id in interview_sessions:
        del interview_sessions[session_id]
        return True
    return False


def get_all_sessions() -> List[Dict]:
    """
    获取所有面试会话

    Returns:
        list: 会话列表
    """
    return [session.to_dict() for session in interview_sessions.values()]
