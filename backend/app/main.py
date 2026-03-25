from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from contextlib import asynccontextmanager

from .ingestion import process_content, refine_content_with_feedback, get_staging_data, clear_staging_data
from .storage import get_vault_data, get_categories, add_category, commit_item_with_category, init_default_categories
from .agent import get_chat_response
from xhs_downloader.application.app import XHS
from .deps import get_xhs_instance, get_llm_instance, get_qa_router_instance
# @asynccontextmanager
# async def lifespan(_app: FastAPI):
#     # Initialize default categories on startup
#     await init_default_categories()
    
#     yield

xhs_client: XHS = None

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

class URLInput(BaseModel):
    url: str
    category: Optional[str] = None

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
async def process_url(input: URLInput):
    """
    Process URL and return structured data for review with progress updates.
    """
    if not input.url:
        raise HTTPException(status_code=400, detail="URL is required")

    from fastapi.responses import StreamingResponse
    import json
    import asyncio

    # Create a queue to pass progress updates
    progress_queue = asyncio.Queue()

    async def process_with_progress():
        """Process content and send progress updates to the queue"""
        def progress_callback(progress, message):
            # Send progress update to the queue
            asyncio.create_task(progress_queue.put((progress, message)))

        try:
            # Process content with progress callback
            result = await process_content(
                url=input.url, 
                category=input.category or "未分类",
                progress_callback=progress_callback
            )
            # Send final result to the queue
            await progress_queue.put((100, "处理完成", result))
        except Exception as e:
            # Send error message to the queue
            await progress_queue.put((100, f"处理失败: {str(e)}", {"error": str(e)}))

    # Start processing in the background
    asyncio.create_task(process_with_progress())

    async def event_generator():
        """Generate SSE events from the progress queue"""
        # Send initial progress
        yield f"data: {json.dumps({'status': 'processing', 'progress': 0, 'message': '开始处理URL'})}\n\n"

        # Listen for progress updates
        while True:
            try:
                # Get progress update from queue with timeout
                item = await asyncio.wait_for(progress_queue.get(), timeout=300.0)
                
                if len(item) == 3:
                    # Final result
                    progress, message, result = item
                    yield f"data: {json.dumps({'status': 'completed', 'result': result})}\n\n"
                    break
                else:
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

@app.post("/chat")
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