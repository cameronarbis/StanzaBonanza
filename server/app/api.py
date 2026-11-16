"""Routes. One poem resource, two representations (docs/DESIGN.md §5)."""

import random
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from .db import corpus_info
from .sampling import draw_poem
from .schemas import CorpusInfo, PoemParams, PoemQuery, PoemResponse

router = APIRouter(prefix="/api")


def wants_text(q: PoemQuery, accept: str) -> bool:
    """
    Content negotiation: ?format= wins (download links can't set headers),
    otherwise the Accept header's q-weighted preference between
    text/plain and application/json decides. Default: JSON.
    """
    if q.format is not None:
        return q.format == "text"
    best, best_quality = "json", 0.0
    for part in accept.split(","):
        media, _, params = part.partition(";")
        media = media.strip()
        quality = 1.0
        for p in params.split(";"):
            k, _, val = p.partition("=")
            if k.strip() == "q":
                try:
                    quality = float(val)
                except ValueError:
                    quality = 0.0
        if media in ("text/plain", "text/*") and quality > best_quality:
            best, best_quality = "text", quality
        elif media in ("application/json", "application/*") and quality > best_quality:
            best, best_quality = "json", quality
    return best == "text"


def render_text(resp: PoemResponse) -> str:
    p = resp.params
    body = "\n\n".join(
        f"{line.text}\n    — {line.author}, “{line.poem}”" for line in resp.lines
    )
    footer = f"StanzaBonanza · v={p.v} a={p.a} τ={p.tau} n={p.n} seed={p.seed}"
    return f"{body}\n\n{footer}\n"


@router.get("/poem", response_model=PoemResponse)
def get_poem(
    request: Request,
    response: Response,
    q: Annotated[PoemQuery, Query()],
):
    seed = q.seed if q.seed is not None else random.getrandbits(31)
    pool = request.app.state.pool
    with pool.connection() as conn:
        info = corpus_info(conn)
        if info["lines"] == 0:
            raise HTTPException(503, "corpus is empty — ingestion has not run yet")
        lines = draw_poem(conn, q, seed)

    poem = PoemResponse(
        params=PoemParams(
            v=q.v, a=q.a, tau=q.tau, n=q.n, seed=seed, exclude=q.exclude
        ),
        corpus_version=info["corpus_version"],
        lines=lines,
    )
    response.headers["Vary"] = "Accept"
    if wants_text(q, request.headers.get("accept", "")):
        return PlainTextResponse(render_text(poem), headers={"Vary": "Accept"})
    return poem


@router.get("/corpus", response_model=CorpusInfo)
def get_corpus(request: Request):
    with request.app.state.pool.connection() as conn:
        return corpus_info(conn)


@router.get("/health")
def get_health(request: Request):
    with request.app.state.pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "db": True}
