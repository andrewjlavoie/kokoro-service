from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=10000)
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"


class BatchRequest(BaseModel):
    items: list[SpeechRequest] = Field(..., min_length=1, max_length=100)


class TagRequest(BaseModel):
    tags: list[str] = []
    label: str | None = None
