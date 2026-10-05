"""Planes server entry point."""

import uvicorn

from webpage import app


if __name__ == "__main__":
    # Keep startup deliberately small; the FastAPI application owns all behavior.
    uvicorn.run(app, host="0.0.0.0", port=8000)
