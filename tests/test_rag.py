import json
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiQueryRetriever, ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import LLMChainExtractor
from langchain_deepseek import ChatDeepSeek
import json

from typing import List

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func

from sqlalchemy.orm import declarative_base

import chromadb


from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_classic.chains.hyde.base import HypotheticalDocumentEmbedder
from langchain_core.prompts import PromptTemplate



# ChromaDB setup (Vector DB)

CHROMA_PATH = "/home/jhli/knowledge-helper/vault/chroma_db"

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

embeddings = HuggingFaceEmbeddings(model_name="/home/jhli/all-in-rag/bge-small-zh-v1.5")

# 1. 连接到你现有的 ChromaDB
vectorstore = Chroma(
    client=chroma_client,
    collection_name="fragmented_knowledge", # 替换为你实际的 collection 名字
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH
)



# 1. 定义生成“假设性文档”的提示词（针对中文优化）
hyde_prompt_template = """请针对以下问题写一个简短的、专业的百科全书式的回答，用于知识库检索：
问题：{question}
回答："""

prompt = PromptTemplate(input_variables=["question"], template=hyde_prompt_template)

# 2. 初始化 LLM（用于生成假答案）
llm = ChatDeepSeek(temperature=0, model="deepseek-chat", api_key="") # 替换为你的 DeepSeek API 密钥 

# 3. 创建 HyDE Embeddings 对象
# 它会包装你原有的 HuggingFace BGE 模型
hyde_embeddings = HypotheticalDocumentEmbedder.from_llm(
    llm=llm,
    base_embeddings=embeddings, # 你之前定义的 BGE 模型
    custom_prompt=prompt
)

# 4. 将其包装成检索器
def test_hyde_retrieval(query: str, k=3):
    print(f"\n--- [5] HyDE 假设性文档检索 (k={k}) ---")
    
    # 注意：这里的 vectorstore 还是你之前的 Chroma 对象
    # 但我们使用 hyde_embeddings 作为检索时的转换器
    # 实际上是用 hyde_embeddings.embed_query(query) 替换了原来的向量化过程
    
    # 也可以直接创建新的 Chroma 对象封装
    hyde_vectorstore = Chroma(
        client=chroma_client,
        collection_name="your_collection_name",
        embedding_function=hyde_embeddings, # 注入 HyDE 逻辑
    )
    
    retriever = hyde_vectorstore.as_retriever(search_kwargs={"k": k})
    docs = retriever.invoke(query)
    
    for i, doc in enumerate(docs):
        print(f"结果 {i+1}: {doc.page_content[:100]}...")
    return docs

def test_basic_retrieval(query: str, k=3):
    print(f"\n--- [1] 基础相似度检索 (k={k}) ---")
    retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": k})
    docs = retriever.invoke(query)
    for i, doc in enumerate(docs):
        print(f"结果 {i+1}: {doc.page_content[:100]}...")
    return docs

def test_mmr_retrieval(query: str, k=3, fetch_k=10):
    print(f"\n--- [2] MMR 多样性检索 (k={k}) ---")
    # fetch_k 是先获取的候选文档数，k 是最终过滤出的最不相似但相关的文档数
    retriever = vectorstore.as_retriever(
        search_type="mmr", 
        search_kwargs={'k': k, 'fetch_k': fetch_k}
    )
    docs = retriever.invoke(query)
    for i, doc in enumerate(docs):
        print(f"结果 {i+1}: {doc.page_content[:100]}...")
    return docs

def test_multiquery_retrieval(query: str, llm):
    print(f"\n--- [3] 多查询改写检索 ---")
    retriever = MultiQueryRetriever.from_llm(
        retriever=vectorstore.as_retriever(),
        llm=llm
    )
    docs = retriever.invoke(query)
    print(f"汇总召回了 {len(docs)} 条文档")
    for i, doc in enumerate(docs):
        print(f"结果 {i+1}: {doc.page_content[:100]}...")
    return docs

def test_threshold_retrieval(query: str, threshold=0.5):
    print(f"\n--- [4] 分数阈值检索 (Score > {threshold}) ---")
    # search_type="similarity_score_threshold"
    retriever = vectorstore.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={'score_threshold': threshold, 'k': 3}
    )
    docs = retriever.invoke(query)
    if not docs:
        print("未找到符合阈值的文档")
    for i, doc in enumerate(docs):
        print(f"结果 {i+1}: {doc.page_content[:100]}...")
    return docs

def run_all_tests(query: str):
    print(f"🔎 测试问题: {query}")
    
    # 初始化 LLM (用于 Multi-Query)
    # 注意：确保你的环境变量中有 OPENAI_API_KEY
    
    # 执行测试
    test_basic_retrieval(query)
    test_mmr_retrieval(query)
    test_multiquery_retrieval(query, llm)
    test_threshold_retrieval(query, threshold=0.6) # 根据你的 bge 模型调整阈值
    test_hyde_retrieval(query)

if __name__ == "__main__":
    # 填入你数据库中可能存在的一个问题进行测试
    sample_query = "agent的记忆系统"
    run_all_tests(sample_query)
