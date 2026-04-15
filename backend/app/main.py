from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uuid
from datetime import datetime

from .ingestion import process_content, refine_content_with_feedback, get_staging_data, clear_staging_data
from .storage import get_vault_data, get_categories, add_category, commit_item_with_category, init_default_categories, delete_vault_item_data
from .agent import get_chat_response
from xhs_downloader.application.app import XHS
from .deps import get_xhs_instance, get_llm_instance, get_qa_router_instance
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
    client = await get_xhs_instance()
    llm = await get_llm_instance()
    qa_router = await get_qa_router_instance()
    async with client: 
        print("XHS 全局实例已进入上下文 (__aenter__ 已执行)")
        yield

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
    Commit approved Q&A to storage with category.
    """
    # Validate that the data matches staging (optional security check)
    staging_data = get_staging_data(item.id)
    if staging_data:
        # Use the staging data or the provided data
        success = await commit_item_with_category(
            staging_data["items"], staging_data["category"]
        )
        if success:
            # Clear staging data after successful commit
            clear_staging_data(item.id)
    else:
        # No staging data found, commit directly
        success = False

    return {"status": "success" if success else "failed"}

@app.get("/api/vault")
async def get_vault(category: Optional[str] = None):
    """
    Get approved items from the knowledge vault, optionally filtered by category.
    """
    data = await get_vault_data(category)
    return {"items": data}


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
        get_chat_response(input.message, input.referenced_ids),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
