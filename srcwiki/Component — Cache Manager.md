# Component — Cache Manager

#component #cache

**Location:** `src/cache/`
**Files:** `manager.py`, `__init__.py`

## Purpose

The cache manager provides content-addressed audio caching. It stores synthesized WAV files on disk and tracks metadata in MongoDB. Identical synthesis requests (same text, voice, speed, language) return cached audio instantly without running the TTS model.

## Cache Key

The cache key is a SHA-256 hash of a canonical string:

```python
canonical = f"{text}|{voice}|{speed:.1f}|{lang_code}"
cache_key = hashlib.sha256(canonical.encode()).hexdigest()
```

> [!TIP]
> Speed is formatted to 1 decimal place (`.1f`), so `1.0` and `1.00` produce the same key. The pipe `|` separator ensures `"hello|af"` and `"hello"` with voice `"af"` can't collide.

## File Storage

Files are stored in a sharded directory structure under `CACHE_DIR` (default: `/app/audio_cache`):

```
/app/audio_cache/
├── {hash[0:2]}/
│   └── {full_hash}.wav
```

The first two hex chars of the hash create 256 possible subdirectories, preventing filesystem performance degradation from too many files in a single directory.

## Settings

Cache behavior is controlled by settings stored in MongoDB (`settings` collection, `_id: "cache"`). Settings are loaded into memory at startup and can be updated at runtime via the API.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Master switch for caching |
| `min_text_length` | `10` | Skip caching text shorter than this (e.g., "ok", "yes") |
| `max_text_length` | `5000` | Skip caching text longer than this |
| `max_audio_duration` | `120` | Max audio duration in seconds to cache |
| `max_file_size_mb` | `50` | Per-file WAV size limit (MB) |
| `max_total_size_mb` | `1024` | Total cache disk usage cap (1 GB) |
| `max_entries` | `5000` | Max number of cached items |
| `ttl_days` | `30` | Auto-expire entries not accessed in N days (0 = never) |

### Settings API

- `GET /settings/cache` — Returns current settings
- `PUT /settings/cache` — Updates settings (only known keys accepted)
- Settings are also exposed in the web UI

## Core Operations

### `lookup(text, voice, speed, lang_code)`
1. Compute cache key
2. Query MongoDB for matching `cache_key`
3. If found, verify the WAV file exists on disk
   - File exists: increment `hit_count`, update `last_accessed_at`, return `(doc, path)`
   - File missing: delete stale MongoDB entry, return `(None, None)`
4. If not found: return `(None, None)`

### `store(text, voice, speed, wav_bytes, duration, sample_rate, lang_code)`
1. Check `should_cache()` — respects all settings (enabled, text length, duration, file size, total size, entry count)
2. Compute cache key
3. Write WAV file to sharded directory
4. Insert metadata document into MongoDB
5. On duplicate key error (race condition with concurrent identical requests): return the existing document

### `should_cache(text, wav_bytes=None, duration=None)`
Checks all configured limits before allowing a cache store:

```
enabled == True?
  └── text length >= min_text_length?
      └── text length <= max_text_length?
          └── duration <= max_audio_duration?
              └── file size <= max_file_size_mb?
                  └── entry count < max_entries?
                      └── total size < max_total_size_mb?
                          └── True (allow caching)
```

If MongoDB is unavailable, returns `True` (but the store will fail silently).

### `enforce_ttl()`
Removes cache entries that haven't been accessed within `ttl_days`:

1. Query all entries where `last_accessed_at < (now - ttl_days)`
2. For each expired entry: delete the WAV file, then delete the MongoDB document
3. Return count of removed entries

Triggered manually via `POST /settings/cache/ttl-cleanup`.

### `list_entries(search, tag, voice, lang_code, sort_by, sort_order, skip, limit)`
Query cache entries with:
- **Text search**: MongoDB `$text` search on the `text` field
- **Tag filter**: exact match on `tags` array
- **Voice filter**: exact match on `voice`
- **Language filter**: exact match on `lang_code`
- **Sorting**: by `created_at`, `hit_count`, `file_size_bytes`, `audio_duration_sec`, `voice`, or `last_accessed_at`

### `update_tags(cache_id, tags, label)`
Update the `tags` list and/or `label` string on a cache entry. Tags enable organizing cached audio as a snippet library.

### `delete_entry(cache_id)`
Delete the WAV file from disk and remove the MongoDB document.

## MongoDB Cache Document Schema

```json
{
    "cache_key": "a1b2c3...",        // SHA-256 hash (unique index)
    "text": "Hello world",           // original input text
    "voice": "af_heart",             // voice ID used
    "speed": 1.0,                    // speed multiplier
    "lang_code": "a",                // language code
    "audio_duration_sec": 1.23,      // audio length in seconds
    "sample_rate": 24000,            // always 24000
    "file_path": "a1/a1b2c3...wav",  // relative path under CACHE_DIR
    "file_size_bytes": 59132,        // WAV file size
    "tags": [],                      // user-defined tags
    "label": null,                   // optional user-defined label
    "hit_count": 0,                  // times served from cache
    "created_at": "2025-01-01T...",  // creation timestamp
    "last_accessed_at": "2025-01-01T..." // last cache hit timestamp
}
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `AUDIO_CACHE_DIR` | `/app/audio_cache` | Filesystem path for cached WAV files |

## Related Pages

- [[Data Flow]] — How cache fits into request lifecycle
- [[API — Cache Endpoints]] — HTTP endpoints for cache management
- [[Component — Database Layer]] — MongoDB cache collection indexes
