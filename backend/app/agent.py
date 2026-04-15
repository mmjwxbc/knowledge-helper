import os
import json
import math
import re
from typing import TypedDict, List, Annotated, Sequence, Dict, Any, Union, Optional
from langchain_openai import OpenAIEmbeddings
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from .storage import collection, embeddings, get_items_by_ids, get_filtered_knowledge_items
from .deps import get_llm_instance
load_dotenv()

TOP_K = 4

def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())

def _compute_bm25_scores(query: str, documents: List[str]) -> List[float]:
    tokenized_docs = [_tokenize(doc) for doc in documents]
    query_tokens = _tokenize(query)
    if not tokenized_docs or not query_tokens:
        return [0.0 for _ in documents]

    avgdl = sum(len(doc) for doc in tokenized_docs) / max(len(tokenized_docs), 1)
    if avgdl == 0:
        return [0.0 for _ in documents]

    k1 = 1.5
    b = 0.75
    doc_freq: Dict[str, int] = {}
    for doc in tokenized_docs:
        for token in set(doc):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    total_docs = len(tokenized_docs)
    scores: List[float] = []
    for doc in tokenized_docs:
        doc_len = len(doc)
        term_freq: Dict[str, int] = {}
        for token in doc:
            term_freq[token] = term_freq.get(token, 0) + 1

        score = 0.0
        for token in query_tokens:
            if token not in term_freq:
                continue
            df = doc_freq.get(token, 0)
            idf = math.log(1 + ((total_docs - df + 0.5) / (df + 0.5)))
            tf = term_freq[token]
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (doc_len / avgdl))
            score += idf * (numerator / denominator)
        scores.append(score)
    return scores

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if vec_a is None or vec_b is None:
        return 0.0
    if len(vec_a) == 0 or len(vec_b) == 0 or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def _normalize_scores(scores: List[float]) -> List[float]:
    if not scores:
        return []
    min_score = min(scores)
    max_score = max(scores)
    if math.isclose(min_score, max_score):
        return [1.0 if max_score > 0 else 0.0 for _ in scores]
    return [(score - min_score) / (max_score - min_score) for score in scores]

# Define State
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "The messages in the conversation"]
    referenced_ids: Optional[List[int]]
    retrieval_category: Optional[str]
    retrieval_tags: Optional[List[str]]
    context: List[str]
    retrieval_summary: str
    answer: str

# Define Nodes
async def search_db_node(state: AgentState):
    """
    Check if user selected specific IDs from frontend.
    """
    referenced_ids = state.get("referenced_ids", [])
    if referenced_ids:
        # Fetch directly from SQL DB
        items = await get_items_by_ids(referenced_ids)
        contexts = [
            f"Q: {item['question']}\nA: {item['answer']}\nTags: {', '.join(item.get('tags', []))}"
            for item in items
        ]
        return {"context": contexts}
    
    return {"context": []}

async def rag_retrieve_node(state: AgentState):
    """
    Retrieve relevant information with metadata filtering and hybrid scoring.
    """
    last_message = state["messages"][-1].content
    category = state.get("retrieval_category")
    tags = state.get("retrieval_tags") or []

    candidate_items = await get_filtered_knowledge_items(category=category, tags=tags)
    current_context = state.get("context", [])
    if not candidate_items:
        summary_parts = []
        if category:
            summary_parts.append(f"category={category}")
        if tags:
            summary_parts.append(f"tags={','.join(tags)}")
        retrieval_summary = "未找到符合过滤条件的知识" if summary_parts else "知识库中没有可用候选"
        return {"context": current_context, "retrieval_summary": retrieval_summary}

    query_vector = embeddings.embed_query(last_message)
    candidate_ids = [str(item["id"]) for item in candidate_items]
    chroma_results = collection.get(
        ids=candidate_ids,
        include=["documents", "embeddings", "metadatas"]
    )
    result_ids = chroma_results.get("ids") or []
    result_documents = chroma_results.get("documents")
    result_embeddings = chroma_results.get("embeddings")

    embedding_by_id = {}
    for idx, item_id in enumerate(result_ids):
        embedding_by_id[item_id] = {
            "document": result_documents[idx] if result_documents is not None and idx < len(result_documents) else "",
            "embedding": result_embeddings[idx] if result_embeddings is not None and idx < len(result_embeddings) else None,
        }

    documents = [
        embedding_by_id.get(str(item["id"]), {}).get("document")
        or f"Question: {item['question']}\nAnswer: {item['answer']}"
        for item in candidate_items
    ]
    bm25_scores = _compute_bm25_scores(last_message, documents)
    vector_scores = [
        _cosine_similarity(query_vector, embedding_by_id.get(str(item["id"]), {}).get("embedding"))
        for item in candidate_items
    ]
    normalized_bm25 = _normalize_scores(bm25_scores)
    normalized_vector = _normalize_scores(vector_scores)

    ranked_items = []
    for idx, item in enumerate(candidate_items):
        hybrid_score = 0.55 * normalized_bm25[idx] + 0.45 * normalized_vector[idx]
        ranked_items.append(
            {
                **item,
                "document": documents[idx],
                "hybrid_score": hybrid_score,
            }
        )

    ranked_items.sort(key=lambda item: item["hybrid_score"], reverse=True)
    selected_items = ranked_items[:TOP_K]

    rag_contexts = [
        "\n".join(
            [
                f"Q: {item['question']}",
                f"A: {item['answer']}",
                f"Category: {item.get('category') or '未分类'}",
                f"Tags: {', '.join(item.get('tags', [])) or '无'}",
            ]
        )
        for item in selected_items
    ]

    merged_context = list(dict.fromkeys(current_context + rag_contexts))
    summary_parts = [f"候选 {len(candidate_items)} 条", f"召回 {len(selected_items)} 条"]
    if category:
        summary_parts.append(f"category={category}")
    if tags:
        summary_parts.append(f"tags={','.join(tags)}")

    return {
        "context": merged_context,
        "retrieval_summary": "，".join(summary_parts)
    }

async def generate_node(state: AgentState):
    """
    Generate final response using LLM.
    """
    # llm = ChatDeepSeek(model=os.getenv("MODEL_ID"), temperature=0.7, api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_API_BASE_URL"))
    llm = await get_llm_instance()
    context_str = "\n---\n".join(state["context"])
    retrieval_summary = state.get("retrieval_summary", "")
    system_prompt = f"""
    You are a Fragmented Learning AI Tutor. Your goal is to help users learn based on their collected knowledge.
    
    RETRIEVAL SUMMARY:
    {retrieval_summary}

    CONTEXT FROM DATABASE:
    {context_str}
    
    INSTRUCTIONS:
    1. If context is provided, prioritize answering based on the context.
    2. If the user provided specific 'referenced IDs', those items are extra important.
    3. Keep your answers concise and educational.
    4. If you don't know the answer, say so.
    """
    
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    
    # For streaming, we'll return a placeholder and handle it in the main call
    # But for a standard LangGraph node, it returns the state.
    # To support streaming properly with LangGraph, we can use it as a generator.
    
    response = await llm.ainvoke(messages)
    return {"answer": response.content}

# Define Graph
workflow = StateGraph(AgentState)

workflow.add_node("search_db", search_db_node)
workflow.add_node("rag_retrieve", rag_retrieve_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("search_db")
workflow.add_edge("search_db", "rag_retrieve")
workflow.add_edge("rag_retrieve", "generate")
workflow.add_edge("generate", END)

app_graph = workflow.compile()

async def get_chat_response(
    message: str,
    referenced_ids: Optional[List[int]] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    """
    Generator function for streaming response.
    """
    initial_state = {
        "messages": [HumanMessage(content=message)],
        "referenced_ids": referenced_ids,
        "retrieval_category": category,
        "retrieval_tags": tags or [],
        "context": [],
        "retrieval_summary": "",
        "answer": ""
    }
    
    # We want to stream the output. 
    # Instead of running the whole graph at once, we can use the graph to find nodes.
    # But simplified: run LLM directly with the graph-processed state.
    
    # 1. Run the non-generating nodes
    final_state = await app_graph.ainvoke(initial_state)
    
    # 2. Re-run LLM for streaming
    llm = await get_llm_instance()
    context_str = "\n---\n".join(final_state["context"])
    
    system_prompt = f"""
    You are a Fragmented Learning AI Tutor. Your goal is to help users learn based on their collected knowledge.
    
    RETRIEVAL SUMMARY:
    {final_state.get("retrieval_summary", "")}

    CONTEXT FROM DATABASE:
    {context_str}
    
    INSTRUCTIONS:
    1. If context is provided, prioritize answering based on the context.
    2. If the user provided specific 'referenced IDs', those items are extra important.
    3. Keep your answers concise and educational.
    4. If you don't know the answer, say so.
    """
    
    messages = [SystemMessage(content=system_prompt)] + final_state["messages"]
    
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield f"data: {json.dumps({'content': chunk.content})}\n\n"
    
    yield "data: [DONE]\n\n"
