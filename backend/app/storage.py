import json
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import chromadb
from langchain_openai import OpenAIEmbeddings

# SQL Database setup (SQLite)
DATABASE_URL = "sqlite:///./knowledge_vault.db"
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

Base.metadata.create_all(bind=engine)

# ChromaDB setup (Vector DB)
CHROMA_PATH = "./chroma_db"
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embeddings = OpenAIEmbeddings()

# Collection for our knowledge
collection = chroma_client.get_or_create_collection(name="fragmented_knowledge")

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

async def get_vault_data():
    """
    Fetch all approved knowledge items for the frontend.
    """
    db = SessionLocal()
    try:
        items = db.query(KnowledgeItem).filter(KnowledgeItem.status == "approved").all()
        return [
            {
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "tags": json.loads(item.tags),
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

async def commit_item_with_category(question: str, answer: str, tags: List[str], category: str):
    """
    Commit to SQL and Vector DB with category.
    """
    db = SessionLocal()
    try:
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
    default_cats = ["客户信息库", "产品说明书", "财务报表"]
    for cat in default_cats:
        await add_category(cat)
