import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
DRIVER_TZ = timezone(timedelta(hours=5))
FIELDS = ("id", "start", "end", "amount", "payment", "commission")


class TripIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    start: datetime
    end: datetime
    amount: int = Field(gt=0)
    payment: Literal["cash", "card"]
    commission: int = Field(ge=0)

    @model_validator(mode="after")
    def check(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a timezone offset")
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        if self.commission > self.amount:
            raise ValueError("commission cannot exceed amount")
        return self


def summarize(trips):
    s = {"count": 0, "revenue": 0, "commission": 0, "net": 0,
         "cash": {"count": 0, "revenue": 0}, "card": {"count": 0, "revenue": 0}}
    for t in trips:
        s["count"] += 1
        s["revenue"] += t["amount"]
        s["commission"] += t["commission"]
        p = s[t["payment"]]
        p["count"] += 1
        p["revenue"] += t["amount"]
    s["net"] = s["revenue"] - s["commission"]
    return s


def create_app(db_path=None, seed_path=None):
    db_path = str(db_path or ROOT / "data" / "diary.db")
    if seed_path is None:
        seed_path = ROOT / "data" / "trips.json"
    app = FastAPI(title="Driver shift diary")

    def db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    def insert(c, t: TripIn):
        c.execute(
            "INSERT INTO trips (id, start, end, amount, payment, commission, day) VALUES (?,?,?,?,?,?,?)",
            (t.id, t.start.isoformat(), t.end.isoformat(), t.amount, t.payment, t.commission,
             t.start.astimezone(DRIVER_TZ).date().isoformat()),
        )

    def day_trips(day: date):
        with db() as c:
            rows = c.execute("SELECT * FROM trips WHERE day=? ORDER BY start", (day.isoformat(),)).fetchall()
        return [{k: r[k] for k in FIELDS} for r in rows]

    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY, start TEXT NOT NULL, end TEXT NOT NULL,
            amount INTEGER NOT NULL, payment TEXT NOT NULL, commission INTEGER NOT NULL, day TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trips_day ON trips(day)")
        if seed_path and Path(seed_path).exists() and c.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0:
            for item in json.loads(Path(seed_path).read_text()):
                insert(c, TripIn(**item))

    @app.get("/api/trips")
    def list_trips(day: date):
        return day_trips(day)

    @app.get("/api/summary")
    def get_summary(day: date):
        return {"day": day.isoformat(), **summarize(day_trips(day))}

    @app.post("/api/trips", status_code=201)
    def add_trip(trip: TripIn, response: Response):
        with db() as c:
            try:
                insert(c, trip)
                return {"created": True, "trip": trip}
            except sqlite3.IntegrityError:
                old = c.execute("SELECT * FROM trips WHERE id=?", (trip.id,)).fetchone()
        stored = TripIn(**{k: old[k] for k in FIELDS})
        if stored != trip:
            raise HTTPException(409, "trip with this id already exists with different data")
        response.status_code = 200
        return {"created": False, "trip": stored}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "app" / "index.html")

    return app


app = create_app()
