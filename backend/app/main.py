from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uuid
from datetime import datetime
import json
from .ingestion import process_content, refine_content_with_feedback, get_staging_data, clear_staging_data
from .storage import get_vault_data, get_categories, get_all_tags, add_category, commit_item_with_category, commit_to_storage, init_default_categories, delete_vault_item_data, list_chat_conversations, get_chat_conversation, upsert_chat_conversation, delete_chat_conversation, upsert_memory_item, get_memory_item, list_memory_items, delete_memory_item, log_memory_access, mark_knowledge_item_reviewed
from .agent import get_chat_response
from .review import daily_review_cache
from xhs_downloader.application.app import XHS
from .deps import get_xhs_instance, get_llm_instance, get_qa_router_instance

# 面试功能模块
from .interview import (
    create_interview_session,
    get_interview_session,
    update_interview_session,
    delete_interview_session,
    get_all_sessions,
    build_interview_kickoff,
    generate_interview_questions,
    stream_answer_interview_question
)
from .code_downloader import download_code, get_code_structure, is_github_url, is_gitlab_url
from .code_analyzer import analyze_codebase, quick_code_summary
from .interview_sandbox import (
    create_sandbox,
    get_sandbox_info,
    cleanup_sandbox,
    async_cleanup_sandbox
)
# @asynccontextmanager
# async def lifespan(_app: FastAPI):
#     # Initialize default categories on startup
#     await init_default_categories()
#     
#     yield
import time
def log(msg):
    # 日期时间部分（红色）
    time_str = time.strftime("%Y-%m-%d %H:%M:%S")
    red_time = f"\033[31m[{time_str}]\033[0m"
    # 打印
    print(f"{red_time} {msg}")

xhs_client: XHS = None

# 全局任务队列
task_queue: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Initialize default categories on startup
    await init_default_categories()
    await daily_review_cache.startup()
    client = await get_xhs_instance()
    llm = await get_llm_instance()
    qa_router = await get_qa_router_instance()
    async with client: 
        print("XHS 全局实例已进入上下文 (__aenter__ 已执行)")
        yield
    await daily_review_cache.shutdown()

app = FastAPI(title="Fragmented Learning Assistant API", lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProcessInput(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None
    extract_mode: Optional[str] = None

class CorrectInput(BaseModel):
    id: str
    feedback: str

class CommitInput(BaseModel):
    id: str
    question: str
    answer: str
    tags: List[str]
    category: str

class ChatInput(BaseModel):
    message: str
    referenced_ids: Optional[List[int]] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    history: Optional[List[Dict[str, Any]]] = None

class ChatConversationInput(BaseModel):
    id: str
    title: str
    messages: List[Dict[str, Any]]
    category: Optional[str] = None
    tags: Optional[List[str]] = None

class MemoryFactInput(BaseModel):
    fact_key: str
    fact_value: Any
    value_type: Optional[str] = "text"

class MemoryItemInput(BaseModel):
    id: str
    memory_type: str
    scope: str
    title: str
    summary: str
    content: str
    source: str
    tags: Optional[List[str]] = None
    facts: Optional[List[MemoryFactInput]] = None
    source_ref_type: Optional[str] = None
    source_ref_id: Optional[str] = None
    confidence: Optional[float] = 0.7
    importance: Optional[float] = 0.5
    freshness: Optional[float] = 1.0
    status: Optional[str] = "active"

class MemoryAccessInput(BaseModel):
    query_text: str
    query_type: str
    memory_id: str
    score: Optional[float] = None
    selected: Optional[bool] = False

class DailyReviewMarkInput(BaseModel):
    item_id: int

# Category Management Endpoints
@app.get("/api/categories")
async def get_categories_endpoint():
    """
    Get all knowledge categories.
    """
    data = await get_categories()
    return {"categories": data}

@app.post("/api/categories")
async def add_category_endpoint(category_data: dict):
    """
    Add a new knowledge category.
    """
    name = category_data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")

    success = await add_category(name)
    if success:
        return {"status": "success", "message": f"Category '{name}' added"}
    else:
        return {"status": "failed", "message": f"Category '{name}' already exists"}

@app.get("/api/tags")
async def get_tags_endpoint(category: Optional[str] = None):
    """
    Get existing tags in the knowledge vault, optionally filtered by category.
    """
    data = await get_all_tags(category)
    return {"tags": data}

@app.get("/api/memory")
async def get_memory_items_endpoint(
    memory_type: Optional[str] = None,
    scope: Optional[str] = None,
    status: str = "active",
    tag: Optional[str] = None,
    limit: int = 100,
):
    """
    List memory items with optional filters.
    """
    items = await list_memory_items(
        memory_type=memory_type,
        scope=scope,
        status=status,
        tag=tag,
        limit=limit,
    )
    return {"items": items}

@app.get("/api/memory/{memory_id}")
async def get_memory_item_endpoint(memory_id: str):
    """
    Get a single memory item.
    """
    item = await get_memory_item(memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return item

@app.post("/api/memory")
async def upsert_memory_item_endpoint(input: MemoryItemInput):
    """
    Create or update a memory item.
    """
    success = await upsert_memory_item(
        memory_id=input.id,
        memory_type=input.memory_type,
        scope=input.scope,
        title=input.title,
        summary=input.summary,
        content=input.content,
        source=input.source,
        tags=input.tags,
        facts=[fact.model_dump() for fact in (input.facts or [])],
        source_ref_type=input.source_ref_type,
        source_ref_id=input.source_ref_id,
        confidence=input.confidence or 0.7,
        importance=input.importance or 0.5,
        freshness=input.freshness or 1.0,
        status=input.status or "active",
    )
    return {"status": "success" if success else "failed"}

@app.delete("/api/memory/{memory_id}")
async def delete_memory_item_endpoint(memory_id: str):
    """
    Delete a memory item.
    """
    success = await delete_memory_item(memory_id)
    return {"success": success}

@app.post("/api/memory/access-log")
async def log_memory_access_endpoint(input: MemoryAccessInput):
    """
    Log memory retrieval access.
    """
    success = await log_memory_access(
        query_text=input.query_text,
        query_type=input.query_type,
        memory_id=input.memory_id,
        score=input.score,
        selected=bool(input.selected),
    )
    return {"status": "success" if success else "failed"}

# Content Processing Endpoints
@app.post("/api/process")
async def process_url(input: ProcessInput):
    """
    Process URL or pasted text and return structured data for review with progress updates.
    """
    input_url = input.url.strip() if input.url else None
    input_text = input.text.strip() if input.text else None

    if not input_url and not input_text:
        raise HTTPException(status_code=400, detail="URL or text is required")

    from fastapi.responses import StreamingResponse
    import json
    import asyncio

    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Create task object
    task = {
        "id": task_id,
        "url": input_url,
        "text": input_text,
        "source_type": "text" if input_text else "url",
        "category": input.category or "未分类",
        "status": "processing",
        "progress": 0,
        "message": "开始处理文本" if input_text else "开始处理URL",
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat()
    }
    
    # Add to global task queue
    task_queue[task_id] = task

    # Create a queue to pass progress updates
    progress_queue = asyncio.Queue()

    async def process_with_progress():
        """Process content and send progress updates to the queue"""
        def progress_callback(progress, message):
            # Update task status
            task["progress"] = progress
            task["message"] = message
            task["updated"] = datetime.now().isoformat()
            # Send progress update to the queue
            asyncio.create_task(progress_queue.put((progress, message)))

        try:
            # Process content with progress callback
            result = await process_content(
                url=input_url,
                raw_text=input_text,
                category=input.category or "未分类",
                extract_mode=input.extract_mode or "text_and_images",
                progress_callback=progress_callback
            )
            log("完成process url")
            # Update task status
            task["status"] = "completed"
            task["progress"] = 100
            task["message"] = "处理完成"
            task["result"] = result
            task["updated"] = datetime.now().isoformat()
            # Send final result to the queue
            print(f"[完成] 发送最终结果到queue，result类型: {type(result)}")
            await progress_queue.put((100, "处理完成", result))
        except Exception as e:
            # Update task status
            task["status"] = "failed"
            task["progress"] = 100
            task["message"] = f"处理失败: {str(e)}"
            task["error"] = str(e)
            task["updated"] = datetime.now().isoformat()
            # Send error message to the queue
            await progress_queue.put((100, f"处理失败: {str(e)}", {"error": str(e)}))

    # Start processing in the background
    asyncio.create_task(process_with_progress())

    async def event_generator():
        """Generate SSE events from the progress queue"""
        # Send initial progress
        initial_message = "开始处理文本" if input_text else "开始处理URL"
        yield f"data: {json.dumps({'status': 'processing', 'progress': 0, 'message': initial_message})}\n\n"

        # Listen for progress updates
        while True:
            try:
                # Get progress update from queue with timeout
                item = await asyncio.wait_for(progress_queue.get(), timeout=300.0)
                
                if len(item) == 3:
                    # Final result
                    progress, message, result = item
                    print(f"[SSE] 发送completed事件, result类型: {type(result)}")
                    yield f"data: {json.dumps({'status': 'completed', 'result': result})}\n\n"
                    break
                else:
                    # Progress update
                    progress, message = item
                    yield f"data: {json.dumps({'status': 'processing', 'progress': progress, 'message': message})}\n\n"
            except asyncio.TimeoutError:
                # Update task status
                task["status"] = "failed"
                task["message"] = "处理超时"
                task["error"] = "处理超时"
                task["updated"] = datetime.now().isoformat()
                # Send timeout message
                yield f"data: {json.dumps({'status': 'error', 'message': '处理超时'})}\n\n"

                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

@app.get("/api/tasks")
async def get_tasks():
    """
    Get all tasks in the queue.
    """
    return {"tasks": list(task_queue.values())}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """
    Get a specific task by ID.
    """
    if task_id not in task_queue:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task_queue[task_id]}

@app.get("/api/tasks/{task_id}/progress")
async def get_task_progress(task_id: str):
    """
    Get progress updates for a specific task via SSE.
    """
    if task_id not in task_queue:
        raise HTTPException(status_code=404, detail="Task not found")

    from fastapi.responses import StreamingResponse
    import json
    import asyncio

    task = task_queue[task_id]

    async def event_generator():
        """Generate SSE events for the task progress"""
        # Send current task status
        if task["status"] == "processing":
            yield f"data: {json.dumps({'status': 'processing', 'progress': task['progress'], 'message': task['message']})}\n\n"
        elif task["status"] == "completed" and "result" in task:
            yield f"data: {json.dumps({'status': 'completed', 'result': task['result']})}\n\n"
        elif task["status"] == "failed" and "error" in task:
            yield f"data: {json.dumps({'status': 'error', 'message': task['error']})}\n\n"

        # If task is not completed, wait for updates
        if task["status"] == "processing":
            # Create a queue to receive progress updates
            progress_queue = asyncio.Queue()

            # Function to check task status periodically
            async def check_task_status():
                while task["status"] == "processing":
                    await asyncio.sleep(1)  # Check every second
                    # Send progress update if it has changed
                    await progress_queue.put((task["progress"], task["message"]))

            # Start checking task status
            asyncio.create_task(check_task_status())

            # Listen for progress updates
            while task["status"] == "processing":
                try:
                    # Get progress update from queue with timeout
                    item = await asyncio.wait_for(progress_queue.get(), timeout=300.0)
                    
                    # Progress update
                    progress, message = item
                    yield f"data: {json.dumps({'status': 'processing', 'progress': progress, 'message': message})}\n\n"
                except asyncio.TimeoutError:
                    # Send timeout message
                    yield f"data: {json.dumps({'status': 'error', 'message': '处理超时'})}\n\n"
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

@app.post("/api/process/correct")
async def correct_process(input: CorrectInput):
    """
    Re-process content with user feedback.
    """
    if not input.id:
        raise HTTPException(status_code=400, detail="Processing ID is required")

    result = await refine_content_with_feedback(input.id, input.feedback)
    return result

# Commit and Vault Endpoints
@app.post("/api/commit")
async def commit_endpoint(item: CommitInput):
    """
    Commit a single approved Q&A item to storage with category and tags.
    """
    clean_tags = [tag.strip() for tag in item.tags if isinstance(tag, str) and tag.strip()]
    success = await commit_to_storage(
        question=item.question,
        answer=item.answer,
        tags=clean_tags,
        category=item.category
    )

    return {"status": "success" if success else "failed"}

@app.get("/api/vault")
async def get_vault(category: Optional[str] = None):
    """
    Get approved items from the knowledge vault, optionally filtered by category.
    """
    data = await get_vault_data(category)
    return {"items": data}

@app.get("/api/review/daily")
async def get_daily_review():
    """
    Get today's daily review snapshot from cache.
    """
    payload = await daily_review_cache.get_payload()
    return payload

@app.post("/api/review/daily/mark")
async def mark_daily_review_item(input: DailyReviewMarkInput):
    """
    Mark a knowledge item as reviewed and update today's cache in place.
    """
    updated = await mark_knowledge_item_reviewed(input.item_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    payload = await daily_review_cache.mark_item_reviewed(input.item_id)
    if payload is None:
        payload = await daily_review_cache.get_payload()

    return {
        "status": "success",
        "item": updated,
        "daily_review": payload,
    }


@app.delete("/api/vault/delete")
async def delete_vault_item(item: dict):
    """
    Delete an approved item from the knowledge vault.
    """
    item_id = item.get("item_id")
    success = await delete_vault_item_data(item_id)
    return {"success": success}

# Legacy Endpoints (kept for backward compatibility)
@app.post("/process")
async def process_input(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Body(None)
):
    """
    Process input file or URL and return structured Q&A.
    """
    if not file and not url:
        raise HTTPException(status_code=400, detail="Either file or URL must be provided.")

    result = await process_content(file=file, url=url)
    return result

@app.post("/commit")
async def commit_input(item: CommitInput):
    """
    Commit structured Q&A to dual storage (SQL + Vector).
    """
    staging_data = get_staging_data(item.id)
    success = await commit_item_with_category(staging_data["items"], staging_data["category"])
    return {"status": "success" if success else "failed"}

@app.get("/vault")
async def get_vault_legacy():
    """
    Get all items from SQL database for Knowledge Vault.
    """
    data = await get_vault_data()
    return data

@app.post("/api/chat")
async def chat(input: ChatInput):
    """
    Chat with AI tutor using LangGraph Agent.
    """
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        get_chat_response(
            message=input.message,
            referenced_ids=input.referenced_ids,
            category=input.category,
            tags=input.tags,
            history=input.history,
        ),
        media_type="text/event-stream"
    )

@app.get("/api/chat/conversations")
async def get_chat_conversations():
    """
    List saved chat conversations.
    """
    data = await list_chat_conversations()
    return {"conversations": data}

@app.get("/api/chat/conversations/{conversation_id}")
async def get_chat_conversation_endpoint(conversation_id: str):
    """
    Get a saved chat conversation.
    """
    data = await get_chat_conversation(conversation_id)
    if not data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return data

@app.post("/api/chat/conversations")
async def save_chat_conversation(input: ChatConversationInput):
    """
    Create or update a saved chat conversation.
    """
    success = await upsert_chat_conversation(
        conversation_id=input.id,
        title=input.title,
        messages=input.messages,
        category=input.category,
        tags=input.tags,
    )
    return {"status": "success" if success else "failed"}

@app.delete("/api/chat/conversations/{conversation_id}")
async def delete_chat_conversation_endpoint(conversation_id: str):
    """
    Delete a saved chat conversation.
    """
    success = await delete_chat_conversation(conversation_id)
    return {"success": success}

# ==================== 面试项目功能 ====================

class InterviewAnalyzeInput(BaseModel):
    """面试分析输入"""
    code_url: Optional[str] = None  # GitHub/GitLab URL
    difficulty: str = "medium"  # easy/medium/hard
    question_count: int = 10
    category: Optional[str] = None  # 知识库分类
    tags: Optional[List[str]] = None  # 知识库标签

class InterviewAskInput(BaseModel):
    """面试提问输入"""
    question: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None

@app.post("/api/interview/analyze")
async def analyze_interview_code(
    code_url: Optional[str] = Form(None),
    difficulty: str = Form("medium"),
    question_count: int = Form(10),
    file: Optional[UploadFile] = File(None),
):
    """
    分析代码并生成面试问题（SSE 流式响应）
    """
    from fastapi.responses import StreamingResponse
    import asyncio

    if not code_url and not file:
        raise HTTPException(status_code=400, detail="需要提供代码 URL 或上传压缩包")

    # 验证输入
    if code_url:
        if not (is_github_url(code_url) or is_gitlab_url(code_url)):
            raise HTTPException(status_code=400, detail="仅支持 GitHub 或 GitLab URL")
        if file:
            raise HTTPException(status_code=400, detail="URL 和文件不能同时提供")

    # 生成会话 ID
    session_id = str(uuid.uuid4())
    task_id = session_id

    # 创建沙箱
    sandbox_id = create_sandbox()

    # 创建任务和会话
    task = {
        "id": task_id,
        "code_url": code_url,
        "difficulty": difficulty,
        "question_count": question_count,
        "status": "processing",
        "progress": 0,
        "message": "开始分析代码",
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat()
    }
    task_queue[task_id] = task

    create_interview_session(session_id, code_url)

    progress_queue = asyncio.Queue()

    async def process_with_progress():
        """处理代码分析并生成面试问题"""
        def progress_callback(progress, message):
            task["progress"] = progress
            task["message"] = message
            task["updated"] = datetime.now().isoformat()
            asyncio.create_task(progress_queue.put((progress, message)))

        try:
            # 1. 下载代码
            progress_callback(10, "下载代码到沙箱")
            success, message = await download_code(
                sandbox_id,
                url=code_url,
                file=file
            )

            if not success:
                raise Exception(message)

            # 2. 分析代码
            progress_callback(20, "分析代码结构")
            analysis = await analyze_codebase(sandbox_id, progress_callback)

            # 3. 生成面试问题
            progress_callback(80, "生成面试问题")
            questions = await generate_interview_questions(
                analysis,
                difficulty=difficulty,
                count=question_count,
                progress_callback=progress_callback
            )

            # 4. 更新会话
            update_interview_session(session_id, analysis, questions)
            session = get_interview_session(session_id)
            if session is not None:
                await build_interview_kickoff(session)

            # 5. 清理沙箱
            progress_callback(95, "清理临时文件")
            await async_cleanup_sandbox(sandbox_id)

            # 6. 完成
            task["status"] = "completed"
            task["progress"] = 100
            task["message"] = "分析完成"
            task["updated"] = datetime.now().isoformat()

            session = get_interview_session(session_id)
            result = session.to_dict() if session is not None else {
                "session_id": session_id,
                "analysis": analysis.to_dict(),
                "questions": [q.model_dump() for q in questions]
            }
            await progress_queue.put((100, "分析完成", result))

        except Exception as e:
            # 错误处理
            task["status"] = "failed"
            task["progress"] = 100
            task["message"] = f"分析失败: {str(e)}"
            task["error"] = str(e)
            task["updated"] = datetime.now().isoformat()

            await progress_queue.put((100, f"分析失败: {str(e)}", {"error": str(e)}))

    # 启动后台处理
    asyncio.create_task(process_with_progress())

    async def event_generator():
        """生成 SSE 事件"""
        yield f"data: {json.dumps({'status': 'processing', 'progress': 0, 'message': '开始分析代码'})}\n\n"

        while True:
            try:
                item = await asyncio.wait_for(progress_queue.get(), timeout=600.0)

                if len(item) == 3:
                    # 最终结果
                    progress, message, result = item
                    yield f"data: {json.dumps({'status': 'completed', 'result': result})}\n\n"
                    break
                else:
                    # 进度更新
                    progress, message = item
                    yield f"data: {json.dumps({'status': 'processing', 'progress': progress, 'message': message})}\n\n"

            except asyncio.TimeoutError:
                task["status"] = "failed"
                task["message"] = "分析超时"
                task["error"] = "分析超时"
                task["updated"] = datetime.now().isoformat()

                yield f"data: {json.dumps({'status': 'error', 'message': '分析超时'})}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/interview/session/{session_id}")
async def get_interview_session_endpoint(session_id: str):
    """
    获取面试会话详情
    """
    session = get_interview_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    return session.to_dict()


@app.get("/api/interview/sessions")
async def get_all_interview_sessions():
    """
    获取所有面试会话
    """
    return {"sessions": get_all_sessions()}


@app.delete("/api/interview/session/{session_id}")
async def delete_interview_session_endpoint(session_id: str):
    """
    删除面试会话
    """
    success = delete_interview_session(session_id)
    return {"success": success}


@app.post("/api/interview/ask")
async def ask_interview_question_stream(session_id: str, input: InterviewAskInput):
    """
    向面试会话提问（SSE 流式响应）
    """
    from fastapi.responses import StreamingResponse

    session = get_interview_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    return StreamingResponse(
        stream_answer_interview_question(
            question=input.question,
            session_id=session_id,
            category=input.category,
            tags=input.tags
        ),
        media_type="text/event-stream"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
