import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt
from pydantic import BaseModel, StringConstraints
from typing import Annotated

from .advanced import ask_advanced
from .agent import OLLAMA_URL, AgentError, ask

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")
markdown = MarkdownIt("commonmark", {"html": False, "breaks": True}).disable("image")

app = FastAPI(title="Gene Expression Explorer")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)
    ]
    is_advanced: bool = False


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    try:
        with httpx.Client(base_url=OLLAMA_URL, trust_env=False) as client:
            handler = ask_advanced if request.is_advanced else ask
            result = handler(request.question, client)
        return {**result, "answer_html": markdown.render(result["answer"])}
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "The local model took too long. Please try again.") from exc
    except httpx.HTTPError as exc:
        logger.warning("Ollama request failed: %s", exc)
        raise HTTPException(503, "The local model is unavailable. Check the Ollama logs.") from exc
    except AgentError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Unexpected Ollama response: %s", exc)
        raise HTTPException(502, "The local model returned an invalid response.") from exc
