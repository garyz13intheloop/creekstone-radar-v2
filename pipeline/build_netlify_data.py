"""
Automated Netlify dataset generator.
Extracts and compresses full historical dataset (100+ days, 8,000+ items)
into a production-grade single-file JSON at netlify/data.json.
Runs daily via GitHub Actions.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

log = logging.getLogger(__name__)


def generate_netlify_data():
    structured = config.STRUCTURED_DIR
    files = sorted([f for f in structured.glob("*.ndjson") if ".old" not in f.name])
    
    all_items = []
    seen_ids = set()

    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                iid = d.get("id")
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    
                    sb_r = d.get("score_breakdown") or {}
                    fp_r = d.get("full_profile") or {}
                    tm_r = d.get("team") or {}
                    m = d.get("metrics") or {}
                    
                    item_min = {
                        "id": iid,
                        "src": d.get("source", ""),
                        "at": d.get("collected_at", ""),
                        "t": d.get("title", ""),
                        "u": d.get("url", ""),
                        "tr": d.get("track", ""),
                        "tr_rs": d.get("track_reason", ""),
                        "sc": float(d.get("score", 0)),
                        "kws": d.get("keywords", []),
                        "hot": d.get("is_trending", False),
                        "new": d.get("is_new", False),
                        "m": {
                            "votes": m.get("votes"),
                            "stars": m.get("stars"),
                            "spd": m.get("stars_today") or m.get("stars_per_day"),
                            "wow": m.get("wow_pct"),
                            "pts": m.get("points"),
                            "likes": m.get("likes"),
                            "bks": m.get("bookmarks"),
                            "downloads": m.get("downloads"),
                        },
                        "sb": {
                            "ai": sb_r.get("ai_native", 0),
                            "nc": sb_r.get("niche", 0),
                            "bz": sb_r.get("business", 0),
                            "tm": sb_r.get("team", 0),
                            "bp": sb_r.get("bonus", 0) - sb_r.get("penalty", 0),
                            "rs": sb_r.get("reason", ""),
                            "p": sb_r.get("plus", []),
                            "mi": sb_r.get("minus", []),
                        } if sb_r else None,
                        "fp": {
                            "ol": fp_r.get("one_liner", ""),
                            "ov": fp_r.get("overview_zh", ""),
                            "bm": fp_r.get("biz_model_zh", ""),
                            "is": fp_r.get("insight_zh", ""),
                            "sn": fp_r.get("score_narrative_zh", ""),
                            "ms": fp_r.get("metrics_summary", ""),
                            "fd": fp_r.get("founder_detail", ""),
                        } if fp_r else None,
                        "tm": {
                            "fds": tm_r.get("founders", []),
                            "fin": tm_r.get("funding_info", ""),
                            "ch": tm_r.get("is_chinese_heritage", False),
                        } if tm_r else None
                    }
                    all_items.append(item_min)
        except Exception as e:
            pass

    # Ensure netlify dir exists
    config.ROOT.mkdir(parents=True, exist_ok=True)
    out_dir = config.ROOT / "netlify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.json"
    
    out_path.write_text(json.dumps(all_items, ensure_ascii=False), encoding="utf-8")
    
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"[netlify] generated {len(all_items)} items -> {out_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    generate_netlify_data()
