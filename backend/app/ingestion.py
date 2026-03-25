import os
import io
import json
import uuid
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from fastapi import UploadFile
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
import docx2txt
from pypdf import PdfReader
import aiohttp
from bs4 import BeautifulSoup
from biliSub.enhanced_bilisub import BiliSubDownloader
from dotenv import load_dotenv
from .utils import read_srt
from .deps import get_xhs_instance, get_qa_router_instance
load_dotenv()

# Models for PydanticOutputParser
class QAItem(BaseModel):
    question: str = Field(description="The question extracted or formulated from the content")
    answer: str = Field(description="The detailed answer corresponding to the question")
    tags: List[str] = Field(description="Relevant tags for the content")

parser = PydanticOutputParser(pydantic_object=QAItem)
bilibili_sub_downloader = BiliSubDownloader({
        "output_formats": ["srt"],
        "use_asr": True,
        "asr_model": "small",
        "concurrency": 2,
        "temp_dir": "/tmp",
        "output_dir": "/home/jhli/knowledge-helper/backend/bilisub_output"
    })


# Global memory cache (replace with Redis in production)
# Structure: {id: {"text": str, "question": str, "answer": str, "tags": List[str], "category": str}}
STAGING_CACHE: Dict[str, Dict] = {}

async def extract_text_from_file(file: UploadFile) -> str:
    content = await file.read()
    filename = file.filename.lower()

    if filename.endswith(".pdf"):
        pdf = PdfReader(io.BytesIO(content))
        text = ""
        for page in pdf.pages:
            text += page.extract_text() or ""
        return text
    elif filename.endswith(".docx"):
        text = docx2txt.process(io.BytesIO(content))
        return text
    else:
        return content.decode("utf-8", errors="ignore")
        
async def extract_text_from_url(url: str) -> tuple[bool, str]:
    if "bilibili" in url:
        # print("正在解析视频URL...")
        tasks = bilibili_sub_downloader.parse_input(url)
        
        if not tasks:
            return False, "Unable to parse video URL."
        
        # print(f"开始处理 {len(tasks)} 个视频...")
        await bilibili_sub_downloader.process_tasks(tasks)
        
        # print("\n处理完成!")
        bvid = tasks[0].bvid
        if bilibili_sub_downloader.stats["failed"] > 0:
            return False, "Video failed to download."
        # 显示统计信息
        # print("\n下载统计:")
        # print(f"- 总视频数: {bilibili_sub_downloader.stats['total_videos']}")
        # print(f"- 成功数: {bilibili_sub_downloader.stats['success']}")
        # print(f"- 失败数: {bilibili_sub_downloader.stats['failed']}")
        text = open(os.path.join("/home/jhli/knowledge-helper/backend/bilisub_output", bvid, f"{bvid}.srt"), "r", encoding="utf-8").read()
        return True, read_srt(text)
    elif "xiaohongshu" in url:
        xhs_client = await get_xhs_instance()
        xhs_result = await xhs_client.extract(url, True)
        return True, xhs_result[0]["作品描述"]
    else:
        return False, "Unsupported URL type."
async def _refine_content_with_llm(text: str, feedback: str = None) -> Optional[QAItem]:
    """
    Use LLM to refine content into structured Q&A.
    """
    try:
        llm = ChatDeepSeek(
            model=os.getenv("MODEL_ID"),
            temperature=0.7,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE_URL")
        )

        # Classification Prompt
        classification_prompt = f"""
        Analyze the following content and classify it into one of these three categories:
        1. Isolated Question (An explicit question found in the text)
        2. Fact Description (A factual statement or piece of information)
        3. Q&A Pair (A question followed by its answer)

        Content: {text[:2000]}

        Return only the category name.
        """

        category_response = await llm.ainvoke([HumanMessage(content=classification_prompt)])
        category = category_response.content.strip()

        # Refining Prompt
        refining_system_prompt = """
        You are a professional knowledge assistant. Your task is to extract or formulate a clear question and a concise, high-quality answer from the provided text.
        Format the output as a JSON object with keys: "question", "answer", and "tags".
        Tags should be relevant to the topic.
        {format_instructions}
        """

        if feedback:
            refining_system_prompt += f"""

        User feedback/correction: {feedback}
        Please incorporate this feedback into your extraction and refinement.
        """

        prompt = ChatPromptTemplate.from_template(
            template=refining_system_prompt + "\nContent: {content}\nCategory: {category}"
        )

        chain = prompt | llm | parser

        refined_data = await chain.ainvoke({
            "content": text[:3000],
            "category": category,
            "format_instructions": parser.get_format_instructions()
        })

        return refined_data
    except Exception as e:
        print(f"Error in LLM refinement: {str(e)}")
        return None

async def process_content(file: Optional[UploadFile] = None, url: Optional[str] = None, category: str = "未分类"):
    """
    Process content from file or URL and return structured data for review.
    """
    text = ""
    if file:
        text = await extract_text_from_file(file)
    elif url:
        success, text = await extract_text_from_url(url)
        if not success:
            return {"error": text}

    if not text:
        return {"error": "No text extracted from input"}
    qa_router = await get_qa_router_instance()
    results = await qa_router.route_and_process(text)
    # refined_data = await _refine_content_with_llm(text)

    # if not refined_data:
        # return {"error": "Failed to refine content"}

    # Generate unique ID for this processing session
    processing_id = str(uuid.uuid4())

    # Store in cache for potential corrections
    STAGING_CACHE[processing_id] = {
        "text": text,
        "items": results.items,
        "category": category
    }

    # Generate preview (first 200 chars of answer)
    preview = f"问题: {results.items[0].question}\n\n答案: {results.items[0].answer[:200]}..."

    return {
        "id": processing_id,
        "questions": [item.question for item in results.items],
        "answers": [item.answer for item in results.items],
        "tags": [item.tags for item in results.items],
        "category": category,
        "preview": preview,
        "status": "reviewing"
    }

async def refine_content_with_feedback(processing_id: str, feedback: str):
    """
    Re-process content with user feedback/corrections.
    """
    if processing_id not in STAGING_CACHE:
        return {"error": "Processing session not found"}

    cached_data = STAGING_CACHE[processing_id]
    text = cached_data["text"]
    category = cached_data["category"]

    refined_data = await _refine_content_with_llm(text, feedback)

    if not refined_data:
        return {"error": "Failed to refine content with feedback"}

    # Update cache with new data
    STAGING_CACHE[processing_id] = {
        "text": text,
        "question": refined_data.question,
        "answer": refined_data.answer,
        "tags": refined_data.tags,
        "category": category
    }

    # Generate preview
    preview = f"问题: {refined_data.question}\n\n答案: {refined_data.answer[:200]}..."

    return {
        "id": processing_id,
        "question": refined_data.question,
        "answer": refined_data.answer,
        "tags": refined_data.tags,
        "category": category,
        "preview": preview,
        "status": "reviewing"
    }

def get_staging_data(processing_id: str) -> Optional[Dict]:
    """
    Retrieve cached data for a processing session.
    """
    return STAGING_CACHE.get(processing_id)

def clear_staging_data(processing_id: str):
    """
    Remove data from staging cache after commit.
    """
    if processing_id in STAGING_CACHE:
        del STAGING_CACHE[processing_id]
