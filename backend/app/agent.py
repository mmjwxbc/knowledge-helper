import os
import json
from typing import TypedDict, List, Annotated, Sequence, Dict, Any, Union, Optional
from langchain_openai import OpenAIEmbeddings
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from .storage import collection, embeddings, get_items_by_ids

load_dotenv()

# Define State
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "The messages in the conversation"]
    referenced_ids: Optional[List[int]]
    context: List[str]
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
        contexts = [f"Q: {item['question']}\nA: {item['answer']}" for item in items]
        return {"context": contexts}
    
    return {"context": []}

async def rag_retrieve_node(state: AgentState):
    """
    Retrieve relevant information from ChromaDB if no specific IDs or to supplement context.
    """
    # If we already have some context, maybe we don't need RAG? 
    # Or we can combine them. Let's combine.
    last_message = state["messages"][-1].content
    
    # Generate embedding for retrieval
    query_vector = embeddings.embed_query(last_message)
    
    # Query ChromaDB
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=3
    )
    
    # Extract documents
    rag_contexts = results["documents"][0] if results["documents"] else []
    
    # Merge with existing context
    current_context = state.get("context", [])
    merged_context = list(set(current_context + rag_contexts))
    
    return {"context": merged_context}

async def generate_node(state: AgentState):
    """
    Generate final response using LLM.
    """
    # llm = ChatDeepSeek(model=os.getenv("MODEL_ID"), temperature=0.7, api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_API_BASE_URL"))
    llm = ChatOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model=os.getenv("MODEL_ID"),  # 此处以qwen-plus为例，您可按需更换模型名称。模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
    # other params...
)
    context_str = "\n---\n".join(state["context"])
    system_prompt = f"""
    You are a Fragmented Learning AI Tutor. Your goal is to help users learn based on their collected knowledge.
    
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

async def get_chat_response(message: str, referenced_ids: Optional[List[int]] = None):
    """
    Generator function for streaming response.
    """
    initial_state = {
        "messages": [HumanMessage(content=message)],
        "referenced_ids": referenced_ids,
        "context": [],
        "answer": ""
    }
    
    # We want to stream the output. 
    # Instead of running the whole graph at once, we can use the graph to find nodes.
    # But simplified: run LLM directly with the graph-processed state.
    
    # 1. Run the non-generating nodes
    final_state = await app_graph.ainvoke(initial_state)
    
    # 2. Re-run LLM for streaming
    llm = ChatDeepSeek(model=os.getenv("MODEL_ID"), temperature=0.7, api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_API_BASE_URL"), streaming=True)
    context_str = "\n---\n".join(final_state["context"])
    
    system_prompt = f"""
    You are a Fragmented Learning AI Tutor. Your goal is to help users learn based on their collected knowledge.
    
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
