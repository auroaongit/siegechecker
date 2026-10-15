"""Step 3: the web server your phone talks to.

Run it with:   uvicorn app:app --host 0.0.0.0 --port 8000
Then open http://<your-computer's-IP>:8000 on your phone (same Wi-Fi).
"""

import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import anthropic
from dotenv import load_dotenv

# Load .env BEFORE importing our modules, because they read settings on import.
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from name_reader import NameReadError, read_names  # noqa: E402
from stats import StatsClient  # noqa: E402

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts...
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Set ANTHROPIC_API_KEY in your .env file")
    app.state.stats = StatsClient()
    yield
    # ...and this runs once when it shuts down.
    await app.state.stats.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def home():
    return FileResponse("static/index.html")


@app.post("/api/scan")
async def scan(photo: UploadFile):
    """Photo in, two lists of names out."""
    if photo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Unsupported image type: {photo.content_type}")
    image_bytes = await photo.read()
    try:
        teams = await read_names(image_bytes, photo.content_type)
    except NameReadError as e:
        raise HTTPException(422, str(e))
    except anthropic.AuthenticationError:
        raise HTTPException(502, "Claude API key is missing or wrong. Check ANTHROPIC_API_KEY in .env")
    except anthropic.APIError as e:
        raise HTTPException(502, f"Couldn't reach Claude: {e}")
    return teams


class StatsRequest(BaseModel):
    names: list[str]


@app.post("/api/stats")
async def stats(request: StatsRequest):
    """List of names in, list of stats out (same order)."""
    names = [n for n in request.names if n.strip()][:10]
    results = await app.state.stats.lookup_many(names)
    return [asdict(r) for r in results]
