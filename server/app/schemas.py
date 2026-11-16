"""Request and response models — validation happens here, before any code runs."""

from typing import Literal

from pydantic import BaseModel, Field


class PoemQuery(BaseModel):
    """Query parameters of GET /api/poem (docs/DESIGN.md §5.1)."""

    v: float = Field(description="target valence", ge=0, le=1)
    a: float = Field(description="target arousal", ge=0, le=1)
    tau: float = Field(default=0.12, description="softmax temperature", ge=0.01, le=2.0)
    n: int = Field(default=1, description="line count", ge=1, le=14)
    seed: int | None = Field(default=None, ge=0, lt=2**31)
    exclude: list[str] = Field(default_factory=list, max_length=40)
    format: Literal["json", "text"] | None = Field(
        default=None, description="overrides Accept — download links can't set headers"
    )


class PoemLine(BaseModel):
    text: str
    author: str
    poem: str
    valence: float
    arousal: float


class PoemParams(BaseModel):
    """Echo of the draw's inputs: the recall recipe (docs/DESIGN.md §5.4)."""

    v: float
    a: float
    tau: float
    n: int
    seed: int
    exclude: list[str]


class PoemResponse(BaseModel):
    params: PoemParams
    corpus_version: str
    lines: list[PoemLine]


class CorpusInfo(BaseModel):
    lines: int
    authors: int
    corpus_version: str
    built_at: str
    source: str
