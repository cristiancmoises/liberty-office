"""Synthetic-only request gates around the exact old image's real volume owner.

Never mount this fixture into a production container or expose its loopback port.
"""

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

from liberty.app import create_app

private = create_app()
data = Path(os.environ["LIBERTY_DATA"])
signals = Path("/signals")


@asynccontextmanager
async def lifespan(_):
    async with private.router.lifespan_context(private):
        with sqlite3.connect(data / "fixture.db") as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS mutations(id TEXT PRIMARY KEY, size INTEGER)"
            )
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/fixture/admission")
async def admission():
    return {"ok": True}


@app.post("/fixture/write/{mutation}")
async def write(mutation: str, request: Request):
    if mutation not in {
        "long-upload",
        "disconnected",
        "h2-active",
        "must-not-write",
        "accepted-new",
    }:
        return {"ok": False}
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
    (signals / (mutation + ".started")).write_text(str(size))
    while not (signals / (mutation + ".release")).exists():
        await asyncio.sleep(0.025)
    with sqlite3.connect(data / "fixture.db") as db:
        db.execute("INSERT INTO mutations VALUES(?,?)", (mutation, size))
    (signals / (mutation + ".committed")).write_text(str(size))
    return {"ok": True, "mutation": mutation, "size": size}


app.mount("/", private)
