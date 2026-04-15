import json
from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, func, text
from sqlalchemy.orm import sessionmaker, declarative_base
import chromadb
from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings
# SQL Database setup (SQLite)
DATABASE_URL = "sqlite://///home/jhli/knowledge-helper/vault/sqlite3_db/knowledge_vault.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(String, index=True)
    answer = Column(Text)
    tags = Column(String)  # Stored as JSON string
    category = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="approved") # 'staging', 'approved'

class KnowledgeCategory(Base):
    __tablename__ = "knowledge_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    category = Column(String, nullable=True)
    tags = Column(String, default="[]")
    messages = Column(Text, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class MemoryItem(Base):
    __tablename__ = "memory_items"
    id = Column(String, primary_key=True, index=True)
    memory_type = Column(String, nullable=False, index=True)
    scope = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=False, index=True)
    source_ref_type = Column(String, nullable=True)
    source_ref_id = Column(String, nullable=True, index=True)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.5)
    freshness = Column(Float, default=1.0)
    status = Column(String, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, default=0)

class MemoryTag(Base):
    __tablename__ = "memory_tags"
    id = Column(Integer, primary_key=True, index=True)
    memory_id = Column(String, nullable=False, index=True)
    tag = Column(String, nullable=False, index=True)

class MemoryFact(Base):
    __tablename__ = "memory_facts"
    id = Column(Integer, primary_key=True, index=True)
    memory_id = Column(String, nullable=False, index=True)
    fact_key = Column(String, nullable=False, index=True)
    fact_value = Column(Text, nullable=False)
    value_type = Column(String, default="text")

class MemoryAccessLog(Base):
    __tablename__ = "memory_access_log"
    id = Column(Integer, primary_key=True, index=True)
    query_text = Column(Text, nullable=False)
    query_type = Column(String, nullable=False, index=True)
    memory_id = Column(String, nullable=False, index=True)
    score = Column(Float, nullable=True)
    selected = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# ChromaDB setup (Vector DB)
CHROMA_PATH = "/home/jhli/knowledge-helper/vault/chroma_db"
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embeddings = HuggingFaceEmbeddings(model_name="/home/jhli/all-in-rag/bge-small-zh-v1.5")

# Collection for our knowledge
collection = chroma_client.get_or_create_collection(name="fragmented_knowledge")

def _safe_json_loads(raw: str, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, json.JSONDecodeError):
        return default

def _serialize_memory_item(memory: MemoryItem, tags: List[str], facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": memory.id,
        "memory_type": memory.memory_type,
        "scope": memory.scope,
        "title": memory.title,
        "summary": memory.summary,
        "content": memory.content,
        "source": memory.source,
        "source_ref_type": memory.source_ref_type,
        "source_ref_id": memory.source_ref_id,
        "confidence": float(memory.confidence or 0),
        "importance": float(memory.importance or 0),
        "freshness": float(memory.freshness or 0),
        "status": memory.status,
        "tags": tags,
        "facts": facts,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "last_accessed_at": memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
        "access_count": memory.access_count or 0,
    }

async def commit_to_storage(question: str, answer: str, tags: List[str], category: str = None):
    """
    Commit to SQL and Vector DB in parallel (simulated).
    """
    # 1. SQL Storage
    db = SessionLocal()
    try:
        new_item = KnowledgeItem(
            question=question,
            answer=answer,
            tags=json.dumps(tags),
            category=category or "未分类",
            status="approved"
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        # 2. Vector Storage
        # Generate embedding for question + answer
        text_to_embed = f"Question: {question}\nAnswer: {answer}"
        embedding_vector = embeddings.embed_query(text_to_embed)

        metadata = {"question": question, "tags": ",".join(tags)}
        if category:
            metadata["category"] = category

        collection.add(
            ids=[str(new_item.id)],
            embeddings=[embedding_vector],
            metadatas=[metadata],
            documents=[text_to_embed]
        )

        return True
    except Exception as e:
        print(f"Error committing to storage: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

async def get_vault_data(category=None):
    """
    Fetch approved knowledge items for the frontend, optionally filtered by category.
    """
    db = SessionLocal()
    try:
        query = db.query(KnowledgeItem).filter(KnowledgeItem.status == "approved")
        
        if category:
            query = query.filter(KnowledgeItem.category == category)
        
        items = query.all()
        return [
            {
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "tags": json.loads(item.tags),
                "category": item.category,
                "created_at": item.created_at.isoformat()
            }
            for item in items
        ]
    finally:
        db.close()

async def get_items_by_ids(ids: List[int]):
    """
    Fetch specific knowledge items from SQL DB.
    """
    db = SessionLocal()
    try:
        items = db.query(KnowledgeItem).filter(KnowledgeItem.id.in_(ids)).all()
        return [
            {
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "tags": json.loads(item.tags)
            }
            for item in items
        ]
    finally:
        db.close()

async def get_filtered_knowledge_items(category: Optional[str] = None, tags: Optional[List[str]] = None):
    """
    Fetch approved knowledge items for retrieval, optionally filtered by category and tags.
    """
    db = SessionLocal()
    try:
        query = db.query(KnowledgeItem).filter(KnowledgeItem.status == "approved")

        if category:
            query = query.filter(KnowledgeItem.category == category)

        items = query.all()
        normalized_tags = {
            tag.strip().lower()
            for tag in (tags or [])
            if isinstance(tag, str) and tag.strip()
        }

        results = []
        for item in items:
            try:
                parsed_tags = json.loads(item.tags) if item.tags else []
            except (TypeError, json.JSONDecodeError):
                parsed_tags = []

            if normalized_tags:
                item_tags = {
                    tag.strip().lower()
                    for tag in parsed_tags
                    if isinstance(tag, str) and tag.strip()
                }
                if not item_tags.intersection(normalized_tags):
                    continue

            results.append(
                {
                    "id": item.id,
                    "question": item.question,
                    "answer": item.answer,
                    "tags": parsed_tags,
                    "category": item.category,
                }
            )

        return results
    finally:
        db.close()

async def get_categories():
    """
    Get all knowledge categories.
    """
    db = SessionLocal()
    try:
        categories = db.query(KnowledgeCategory).all()
        return [cat.name for cat in categories]
    finally:
        db.close()

async def get_all_tags(category: Optional[str] = None):
    """
    Get distinct tags already used in the knowledge vault, optionally filtered by category.
    """
    db = SessionLocal()
    try:
        query = db.query(KnowledgeItem.tags).filter(KnowledgeItem.status == "approved")
        if category:
            query = query.filter(KnowledgeItem.category == category)
        items = query.all()
        tag_set = set()
        for (raw_tags,) in items:
            if not raw_tags:
                continue
            try:
                parsed_tags = json.loads(raw_tags)
            except (TypeError, json.JSONDecodeError):
                continue
            for tag in parsed_tags:
                if isinstance(tag, str):
                    clean_tag = tag.strip()
                    if clean_tag:
                        tag_set.add(clean_tag)
        return sorted(tag_set)
    finally:
        db.close()

async def add_category(name: str):
    """
    Add a new knowledge category.
    """
    db = SessionLocal()
    try:
        # Check if category already exists
        existing = db.query(KnowledgeCategory).filter(KnowledgeCategory.name == name).first()
        if existing:
            return False

        new_category = KnowledgeCategory(name=name)
        db.add(new_category)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

async def commit_item_with_category(items: List, category: str):
    """
    Commit to SQL and Vector DB with category.
    """
    db = SessionLocal()
    try:
        for item in items:
            question = item.question
            answer = item.answer
            tags = item.tags
            new_item = KnowledgeItem(
                question=question,
                answer=answer,
                tags=json.dumps(tags),
                category=category,
                status="approved"
            )
            db.add(new_item)
            db.commit()
            db.refresh(new_item)

            # Vector Storage
            text_to_embed = f"Question: {question}\nAnswer: {answer}"
            embedding_vector = embeddings.embed_query(text_to_embed)

            collection.add(
                ids=[str(new_item.id)],
                embeddings=[embedding_vector],
                metadatas=[{"question": question, "tags": ",".join(tags), "category": category}],
                documents=[text_to_embed]
            )

        return True
    except Exception as e:
        print(f"Error committing to storage: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

async def init_default_categories():
    """
    Initialize default categories if they don't exist.
    """
    default_cats = ["agent", "llm", "diffusion and flow"]
    for cat in default_cats:
        await add_category(cat)
        
async def delete_vault_item_data(item_id: str):
    """
    Delete an approved item from the knowledge vault.
    """
    db = SessionLocal()
    try:
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == int(item_id)).first()
        if not item:
            return False
        
        # Delete from SQL database
        db.delete(item)
        db.commit()
        
        # Delete from ChromaDB
        try:
            collection.delete(ids=[str(item_id)])
        except Exception as e:
            print(f"Error deleting from ChromaDB: {str(e)}")
            # Continue even if ChromaDB delete fails
        
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

async def list_chat_conversations():
    """
    List saved chat conversations.
    """
    db = SessionLocal()
    try:
        conversations = (
            db.query(ChatConversation)
            .order_by(ChatConversation.updated_at.desc(), ChatConversation.created_at.desc())
            .all()
        )
        return [
            {
                "id": conversation.id,
                "title": conversation.title,
                "category": conversation.category,
                "tags": json.loads(conversation.tags or "[]"),
                "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            }
            for conversation in conversations
        ]
    finally:
        db.close()

async def get_chat_conversation(conversation_id: str):
    """
    Get a single saved chat conversation.
    """
    db = SessionLocal()
    try:
        conversation = db.query(ChatConversation).filter(ChatConversation.id == conversation_id).first()
        if not conversation:
            return None
        return {
            "id": conversation.id,
            "title": conversation.title,
            "category": conversation.category,
            "tags": json.loads(conversation.tags or "[]"),
            "messages": json.loads(conversation.messages or "[]"),
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        }
    finally:
        db.close()

async def upsert_chat_conversation(
    conversation_id: str,
    title: str,
    messages: List[dict],
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    """
    Create or update a saved chat conversation.
    """
    db = SessionLocal()
    try:
        conversation = db.query(ChatConversation).filter(ChatConversation.id == conversation_id).first()
        serialized_tags = json.dumps(tags or [], ensure_ascii=False)
        serialized_messages = json.dumps(messages or [], ensure_ascii=False)

        if conversation:
            conversation.title = title
            conversation.category = category
            conversation.tags = serialized_tags
            conversation.messages = serialized_messages
        else:
            conversation = ChatConversation(
                id=conversation_id,
                title=title,
                category=category,
                tags=serialized_tags,
                messages=serialized_messages,
            )
            db.add(conversation)

        db.commit()
        db.refresh(conversation)
        return True
    except Exception as e:
        print(f"Error saving chat conversation: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

async def delete_chat_conversation(conversation_id: str):
    """
    Delete a saved chat conversation.
    """
    db = SessionLocal()
    try:
        conversation = db.query(ChatConversation).filter(ChatConversation.id == conversation_id).first()
        if not conversation:
            return False
        db.delete(conversation)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

async def get_retrieval_metadata() -> Dict[str, Any]:
    """
    Get metadata and schema hints for read-only SQL generation.
    """
    categories = await get_categories()
    tags = await get_all_tags()
    return {
        "categories": categories,
        "tags": tags,
        "tables": {
            "knowledge_items": [
                "id INTEGER",
                "question STRING",
                "answer TEXT",
                "tags JSON_STRING",
                "category STRING",
                "created_at DATETIME",
                "status STRING",
            ],
            "chat_conversations": [
                "id STRING",
                "title STRING",
                "category STRING",
                "tags JSON_STRING",
                "messages JSON_STRING",
                "created_at DATETIME",
                "updated_at DATETIME",
            ],
        },
    }

async def execute_readonly_sql(sql: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Execute a validated read-only SQL query against SQLite.
    """
    db = SessionLocal()
    try:
        result = db.execute(text(sql))
        rows = result.mappings().fetchmany(limit)
        return [dict(row) for row in rows]
    finally:
        db.close()

async def upsert_memory_item(
    memory_id: str,
    memory_type: str,
    scope: str,
    title: str,
    summary: str,
    content: str,
    source: str,
    tags: Optional[List[str]] = None,
    facts: Optional[List[Dict[str, Any]]] = None,
    source_ref_type: Optional[str] = None,
    source_ref_id: Optional[str] = None,
    confidence: float = 0.7,
    importance: float = 0.5,
    freshness: float = 1.0,
    status: str = "active",
):
    """
    Create or update a memory item with tags and facts.
    """
    db = SessionLocal()
    try:
        memory = db.query(MemoryItem).filter(MemoryItem.id == memory_id).first()
        if memory is None:
            memory = MemoryItem(id=memory_id)
            db.add(memory)

        memory.memory_type = memory_type
        memory.scope = scope
        memory.title = title
        memory.summary = summary
        memory.content = content
        memory.source = source
        memory.source_ref_type = source_ref_type
        memory.source_ref_id = source_ref_id
        memory.confidence = confidence
        memory.importance = importance
        memory.freshness = freshness
        memory.status = status

        db.flush()

        db.query(MemoryTag).filter(MemoryTag.memory_id == memory_id).delete()
        db.query(MemoryFact).filter(MemoryFact.memory_id == memory_id).delete()

        for tag in sorted({tag.strip() for tag in (tags or []) if isinstance(tag, str) and tag.strip()}):
            db.add(MemoryTag(memory_id=memory_id, tag=tag))

        for fact in facts or []:
            fact_key = str(fact.get("fact_key", "")).strip()
            fact_value = fact.get("fact_value")
            if not fact_key or fact_value is None:
                continue
            db.add(
                MemoryFact(
                    memory_id=memory_id,
                    fact_key=fact_key,
                    fact_value=json.dumps(fact_value, ensure_ascii=False) if isinstance(fact_value, (dict, list)) else str(fact_value),
                    value_type=str(fact.get("value_type", "text")),
                )
            )

        db.commit()
        return True
    except Exception as e:
        print(f"Error upserting memory item: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

async def get_memory_item(memory_id: str):
    """
    Get a single memory item with tags and facts.
    """
    db = SessionLocal()
    try:
        memory = db.query(MemoryItem).filter(MemoryItem.id == memory_id).first()
        if memory is None:
            return None
        tags = [row.tag for row in db.query(MemoryTag).filter(MemoryTag.memory_id == memory_id).all()]
        facts = [
            {
                "fact_key": row.fact_key,
                "fact_value": _safe_json_loads(row.fact_value, row.fact_value),
                "value_type": row.value_type,
            }
            for row in db.query(MemoryFact).filter(MemoryFact.memory_id == memory_id).all()
        ]
        return _serialize_memory_item(memory, tags, facts)
    finally:
        db.close()

async def list_memory_items(
    memory_type: Optional[str] = None,
    scope: Optional[str] = None,
    status: str = "active",
    tag: Optional[str] = None,
    limit: int = 100,
):
    """
    List memory items with optional filters.
    """
    db = SessionLocal()
    try:
        query = db.query(MemoryItem)
        if memory_type:
            query = query.filter(MemoryItem.memory_type == memory_type)
        if scope:
            query = query.filter(MemoryItem.scope == scope)
        if status:
            query = query.filter(MemoryItem.status == status)

        memories = query.order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).limit(limit).all()
        memory_ids = [memory.id for memory in memories]
        tag_rows = db.query(MemoryTag).filter(MemoryTag.memory_id.in_(memory_ids)).all() if memory_ids else []
        fact_rows = db.query(MemoryFact).filter(MemoryFact.memory_id.in_(memory_ids)).all() if memory_ids else []

        tags_by_memory: Dict[str, List[str]] = {}
        for row in tag_rows:
            tags_by_memory.setdefault(row.memory_id, []).append(row.tag)

        facts_by_memory: Dict[str, List[Dict[str, Any]]] = {}
        for row in fact_rows:
            facts_by_memory.setdefault(row.memory_id, []).append(
                {
                    "fact_key": row.fact_key,
                    "fact_value": _safe_json_loads(row.fact_value, row.fact_value),
                    "value_type": row.value_type,
                }
            )

        items = []
        normalized_tag = tag.strip().lower() if tag else None
        for memory in memories:
            memory_tags = tags_by_memory.get(memory.id, [])
            if normalized_tag and normalized_tag not in {t.lower() for t in memory_tags}:
                continue
            items.append(_serialize_memory_item(memory, memory_tags, facts_by_memory.get(memory.id, [])))
        return items
    finally:
        db.close()

async def delete_memory_item(memory_id: str):
    """
    Delete a memory item and its related tags/facts.
    """
    db = SessionLocal()
    try:
        memory = db.query(MemoryItem).filter(MemoryItem.id == memory_id).first()
        if memory is None:
            return False
        db.query(MemoryTag).filter(MemoryTag.memory_id == memory_id).delete()
        db.query(MemoryFact).filter(MemoryFact.memory_id == memory_id).delete()
        db.query(MemoryAccessLog).filter(MemoryAccessLog.memory_id == memory_id).delete()
        db.delete(memory)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

async def log_memory_access(query_text: str, query_type: str, memory_id: str, score: Optional[float] = None, selected: bool = False):
    """
    Log memory retrieval access and update usage counters.
    """
    db = SessionLocal()
    try:
        db.add(
            MemoryAccessLog(
                query_text=query_text,
                query_type=query_type,
                memory_id=memory_id,
                score=score,
                selected=1 if selected else 0,
            )
        )
        memory = db.query(MemoryItem).filter(MemoryItem.id == memory_id).first()
        if memory is not None:
            memory.access_count = (memory.access_count or 0) + 1
            memory.last_accessed_at = func.now()
        db.commit()
        return True
    except Exception as e:
        print(f"Error logging memory access: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()
