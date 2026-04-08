"""Cache CRUD endpoints — list, inspect, download, tag, and delete cached audio."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.api.models import TagRequest
from src.cache import manager as audio_cache

router = APIRouter()


@router.get("/cache")
async def list_cache(
    search: str = "",
    tag: str = "",
    voice: str = "",
    lang_code: str = "",
    sort_by: str = "created_at",
    sort_order: int = -1,
    skip: int = 0,
    limit: int = 50,
):
    """List cached audio entries with search, filtering, and sorting."""

    docs, total = await audio_cache.list_entries(
        search=search,
        tag=tag,
        voice=voice,
        lang_code=lang_code,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return {"entries": docs, "total": total}


@router.get("/cache/{cache_id}/meta")
async def get_cache_meta(cache_id: str):
    """Get metadata for a cached audio entry."""

    doc = await audio_cache.get_entry(cache_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return doc


@router.get("/cache/{cache_id}")
async def get_cached_audio(cache_id: str):
    """Download a cached audio file."""

    doc = await audio_cache.get_entry(cache_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    file_path = audio_cache.CACHE_DIR / doc["file_path"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(file_path, media_type="audio/wav", filename=f"{doc['voice']}_{cache_id[:8]}.wav")


@router.post("/cache/{cache_id}/tag")
async def tag_cache_entry(cache_id: str, req: TagRequest):
    """Update tags and/or label on a cache entry."""

    doc = await audio_cache.update_tags(cache_id, tags=req.tags, label=req.label)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return doc


@router.delete("/cache/{cache_id}")
async def delete_cache_entry(cache_id: str):
    """Remove a cached audio entry and its file."""

    deleted = await audio_cache.delete_entry(cache_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {"deleted": True}
