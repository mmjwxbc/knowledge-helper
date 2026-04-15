import asyncio
import json
import os
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .storage import get_daily_review_items

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover
    Redis = None

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))
DAILY_REVIEW_CACHE_KEY = "knowledge_helper:daily_review"
DAILY_REVIEW_REFRESH_HOUR = 8
DEFAULT_REVIEW_THRESHOLD_DAYS = 7
DEFAULT_LIMIT_PER_CATEGORY = 12
DEFAULT_MAX_CATEGORIES = 12


def _get_today_refresh_time(now: Optional[datetime] = None) -> datetime:
    current = now.astimezone(APP_TIMEZONE) if now else datetime.now(APP_TIMEZONE)
    return current.replace(
        hour=DAILY_REVIEW_REFRESH_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )


def _get_next_refresh_time(now: Optional[datetime] = None) -> datetime:
    current = now.astimezone(APP_TIMEZONE) if now else datetime.now(APP_TIMEZONE)
    today_refresh = _get_today_refresh_time(current)
    if current < today_refresh:
        return today_refresh
    return today_refresh + timedelta(days=1)


class DailyReviewCache:
    def __init__(self):
        self._memory_cache: Optional[Dict[str, Any]] = None
        self._redis: Optional[Redis] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def startup(self):
        await self._init_redis()
        await self.ensure_fresh(force_if_missing=True)
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def shutdown(self):
        if self._refresh_task:
            self._refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._refresh_task
        if self._redis is not None:
            await self._redis.aclose()

    async def _init_redis(self):
        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url or Redis is None:
            return
        try:
            client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = None

    async def _load_cache(self) -> Optional[Dict[str, Any]]:
        if self._redis is not None:
            try:
                raw = await self._redis.get(DAILY_REVIEW_CACHE_KEY)
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return self._memory_cache

    async def _save_cache(self, payload: Dict[str, Any]):
        self._memory_cache = payload
        if self._redis is not None:
            try:
                await self._redis.set(DAILY_REVIEW_CACHE_KEY, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

    def _is_cache_stale(self, payload: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
        if not payload:
            return True

        current = now.astimezone(APP_TIMEZONE) if now else datetime.now(APP_TIMEZONE)
        next_refresh_at = payload.get("next_refresh_at")
        if not next_refresh_at:
            return True

        try:
            return current >= datetime.fromisoformat(next_refresh_at).astimezone(APP_TIMEZONE)
        except ValueError:
            return True

    async def _build_payload(self) -> Dict[str, Any]:
        now = datetime.now(APP_TIMEZONE)
        next_refresh_at = _get_next_refresh_time(now)
        categories = await get_daily_review_items(
            min_days_since_review=DEFAULT_REVIEW_THRESHOLD_DAYS,
            limit_per_category=DEFAULT_LIMIT_PER_CATEGORY,
            max_categories=DEFAULT_MAX_CATEGORIES,
        )
        return {
            "generated_at": now.isoformat(),
            "next_refresh_at": next_refresh_at.isoformat(),
            "threshold_days": DEFAULT_REVIEW_THRESHOLD_DAYS,
            "categories": categories,
            "total_items": sum(category["count"] for category in categories),
        }

    async def ensure_fresh(self, force_if_missing: bool = False) -> Dict[str, Any]:
        async with self._lock:
            payload = await self._load_cache()
            if payload and not self._is_cache_stale(payload):
                return payload
            if payload and not force_if_missing and datetime.now(APP_TIMEZONE) < _get_today_refresh_time():
                return payload

            payload = await self._build_payload()
            await self._save_cache(payload)
            return payload

    async def get_payload(self) -> Dict[str, Any]:
        return await self.ensure_fresh(force_if_missing=True)

    async def mark_item_reviewed(self, item_id: int) -> Optional[Dict[str, Any]]:
        async with self._lock:
            payload = await self._load_cache()
            if not payload:
                return None

            categories = payload.get("categories", [])
            updated_item = None
            next_categories = []
            for category_entry in categories:
                remaining_items = []
                for item in category_entry.get("items", []):
                    if int(item.get("id")) == int(item_id):
                        updated_item = item
                        continue
                    remaining_items.append(item)

                if remaining_items:
                    next_categories.append(
                        {
                            **category_entry,
                            "count": len(remaining_items),
                            "items": remaining_items,
                        }
                    )

            if updated_item is None:
                return None

            payload["categories"] = next_categories
            payload["total_items"] = sum(category["count"] for category in next_categories)
            await self._save_cache(payload)
            return payload

    async def _refresh_loop(self):
        while True:
            now = datetime.now(APP_TIMEZONE)
            next_refresh_at = _get_next_refresh_time(now)
            sleep_seconds = max((next_refresh_at - now).total_seconds(), 30)
            await asyncio.sleep(sleep_seconds)
            try:
                await self.ensure_fresh(force_if_missing=True)
            except Exception:
                pass


daily_review_cache = DailyReviewCache()
