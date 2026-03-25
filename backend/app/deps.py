# deps.py
from xhs_downloader.application.app import XHS  # 你的 XHS 类定义所在的文件
from workflow.qa_router import QARouter
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
import yaml

xhs_client: XHS = None
llm: ChatDeepSeek = None
qa_router: QARouter = None


async def get_xhs_instance():
    """获取全局唯一的 XHS 实例"""
    global xhs_client
    if xhs_client is None:
        # 这里只负责实例化，__init__ 会运行
        with open("/home/jhli/knowledge-helper/config/xhs.yaml", 'r') as f:
            config = yaml.safe_load(f)
        xhs_client = XHS(**config)
    return xhs_client

async def get_llm_instance():
    """获取全局唯一的 ChatDeepSeek 实例"""
    global llm
    if llm is None:
        with open("/home/jhli/knowledge-helper/config/llm.yaml", 'r') as f:
            config = yaml.safe_load(f)
            config = config["DeepSeek"]
            llm = ChatDeepSeek(base_url=config["BASE_URL"], api_key=config["API_KEY"], model_name=config["MODEL_ID"], temperature=0.3, max_tokens=8192)
    return llm

async def get_qa_router_instance():
    """获取全局唯一的 QARouter 实例"""
    global qa_router
    if qa_router is None:
        qa_router = QARouter(llm=await get_llm_instance())
    return qa_router
