"""Preserve ESPN scoring items without guessing stat-ID meanings."""
import json
import math

def extract_scoring_rules(payload):
    items=payload["settings"]["scoringSettings"]["scoringItems"]
    if not isinstance(items,list) or not items:
        raise ValueError("No ESPN scoring items")
    rows=[]
    for item in items:
        if not isinstance(item,dict) or "statId" not in item or "points" not in item:
            raise ValueError("Invalid ESPN scoring item")
        sid=int(item["statId"])
        pts=float(item["points"])
        if not math.isfinite(pts):
            raise ValueError("Nonfinite scoring points")
        # Retain original definition, including position/threshold overrides.
        # Only scoring items are exported; never credentials or raw league payload.
        rows.append({"stat_id":sid,"points":pts,
                     "points_overrides_json":json.dumps(item.get("pointsOverrides",{}),sort_keys=True),
                     "source_item_json":json.dumps(item,sort_keys=True)})
    if len({r["stat_id"] for r in rows})!=len(rows):
        raise ValueError("Duplicate ESPN scoring stat IDs")
    return sorted(rows,key=lambda r:r["stat_id"])
