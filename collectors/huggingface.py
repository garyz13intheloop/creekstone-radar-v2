"""
Hugging Face Trending collector.
Monitors trending models and Spaces via HF Hub API (free, no key needed).
"""
from __future__ import annotations

import logging
import time

import requests

from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
AGENT_KEYWORDS = {
    "agent", "agentic", "tool", "function call", "mcp", "multimodal",
    "vision", "llm", "instruct", "chat", "reasoning", "code",
}


class HuggingFaceCollector(BaseCollector):
    source_id = "huggingface"

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        items: list[SignalItem] = []

        # Trending models
        try:
            resp = requests.get(
                f"{HF_API}/models",
                params={
                    "sort": "trending",
                    "limit": 50,
                    "full": "false",
                    "cardData": "false",
                },
                timeout=20,
            )
            resp.raise_for_status()
            for model in resp.json():
                item = _model_to_item(model, now)
                if item:
                    items.append(item)
            time.sleep(0.5)
        except Exception as e:
            log.error("[huggingface] models fetch failed: %s", e)

        # Trending Spaces (these are often products / demos)
        try:
            resp = requests.get(
                f"{HF_API}/spaces",
                params={
                    "sort": "trending",
                    "limit": 30,
                    "full": "false",
                },
                timeout=20,
            )
            resp.raise_for_status()
            for space in resp.json():
                item = _space_to_item(space, now)
                if item:
                    items.append(item)
        except Exception as e:
            log.error("[huggingface] spaces fetch failed: %s", e)

        log.info("[huggingface] %d items collected", len(items))
        return items


def _model_to_item(model: dict, now: str) -> SignalItem | None:
    model_id = model.get("modelId") or model.get("id", "")
    if not model_id:
        return None

    tags = [t.lower() for t in (model.get("tags") or [])]
    pipeline = (model.get("pipeline_tag") or "").lower()
    downloads = model.get("downloads", 0)
    likes = model.get("likes", 0)

    # Filter: must be text/agent related
    relevant_tags = {"text-generation", "text2text-generation", "question-answering",
                     "conversational", "feature-extraction", "image-text-to-text"}
    if pipeline not in relevant_tags and not any(k in " ".join(tags) for k in AGENT_KEYWORDS):
        return None

    url = f"https://huggingface.co/{model_id}"
    return SignalItem(
        id=make_id("huggingface", url),
        source="huggingface",
        collected_at=now,
        title=model_id,
        url=url,
        description_en=f"HuggingFace model: {model_id}. Pipeline: {pipeline}. Downloads: {downloads:,}.",
        is_trending=True,
        metrics={
            "downloads": downloads,
            "likes": likes,
            "pipeline_tag": pipeline,
            "tags": tags[:10],
            "type": "model",
            "author": model_id.split("/")[0] if "/" in model_id else "",
        },
    )


def _space_to_item(space: dict, now: str) -> SignalItem | None:
    space_id = space.get("id", "")
    if not space_id:
        return None

    likes = space.get("likes", 0)
    if likes < 20:  # filter low-signal spaces
        return None

    url = f"https://huggingface.co/spaces/{space_id}"
    return SignalItem(
        id=make_id("huggingface", url),
        source="huggingface",
        collected_at=now,
        title=space_id,
        url=url,
        description_en=f"HuggingFace Space: {space_id}. Likes: {likes}.",
        is_trending=likes > 200,
        metrics={
            "likes": likes,
            "type": "space",
            "author": space_id.split("/")[0] if "/" in space_id else "",
            "sdk": space.get("sdk", ""),
        },
    )
