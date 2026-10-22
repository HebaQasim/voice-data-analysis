"""Part 6: the FastAPI backend. Every step of the pipeline has its own endpoint, and two endpoints run all of it:
    GET  /                  the web page (part 7)
    POST /datasets          upload a CSV or Excel file -> a table                  (part 1)
    GET  /datasets          the names of the uploaded datasets
    GET  /datasets/{table}  the description of a dataset, the text the LLM reads
    POST /transcribe        a recording -> text                                    (part 5)
    POST /sql/generate      a question -> SQL                                      (part 2)
    POST /sql/execute       SQL -> columns and rows                                (part 3)
    POST /ask               a typed question -> SQL, result and explanation        (part 4)
    POST /ask/voice         a recorded question -> text -> SQL, result and explanation

Start the server:   uvicorn main:app --reload      then open http://127.0.0.1:8000 (or /docs)
Test the endpoints: python main.py
"""
import sqlite3
from typing import Literal

import openai
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from data_analysis import analyze
from datasets import describe_table, list_datasets, load_dataset
from speech import AUDIO_TYPES, transcribe
from sql_runner import run_sql
from text_to_sql import generate_sql

MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB for a dataset or a recording

app = FastAPI(
    title="Voice Data Analysis",
    description="Ask questions about your data by voice or by text, in English or Arabic.",
)


# ---------- The JSON bodies of the requests ----------
# Pydantic checks every request before our code runs: a missing or empty question gets an error 422 automatically
class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    table: str


class SQLRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)


# ---------- Errors ----------
@app.exception_handler(openai.APIError)
def model_unavailable(request, error):
    """Gemini is busy (503), over its quota (429) or not reachable: a clear answer instead of a crash."""
    return JSONResponse(
        status_code=503,
        content={"detail": "The AI model is busy or unavailable right now. Please try again in a minute.",
                 "error": str(error)[:300]},
    )


def read_upload(file, allowed_types):
    """Check the type and the size of an uploaded file, and return its bytes."""
    if not (file.filename or "").lower().endswith(allowed_types):
        raise HTTPException(400, f"Please upload one of these file types: {', '.join(allowed_types)}")
    data = file.file.read(MAX_FILE_SIZE + 1)   # one byte more than the limit tells us if the file is too big
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "The file is bigger than 10 MB.")
    return data


def check_table(table):
    if table not in list_datasets():
        raise HTTPException(404, f"There is no dataset named {table}. Upload it first.")


def transcribe_upload(audio, language):
    """Turn an uploaded recording into text. language: "auto" lets Whisper detect it."""
    data = read_upload(audio, AUDIO_TYPES)
    try:
        return transcribe(data, None if language == "auto" else language)
    except ValueError as error:   # no speech in the recording, or the file is not a real recording
        raise HTTPException(400, str(error))


# ---------- The web page (part 7) ----------
@app.get("/", include_in_schema=False)   # include_in_schema=False: the page is not listed in /docs
def home():
    return FileResponse("static/index.html")


# ---------- Datasets (part 1) ----------
@app.post("/datasets")
def upload_dataset(file: UploadFile):
    """Upload a CSV or Excel file. It becomes a table: the answer has its name and its description."""
    data = read_upload(file, (".csv", ".xlsx"))
    try:
        table = load_dataset(file.filename, data)
    except Exception as error:   # an empty or broken file
        raise HTTPException(400, f"The file could not be read: {error}")
    return {"table": table, "description": describe_table(table)}


@app.get("/datasets")
def get_datasets():
    return {"datasets": list_datasets()}


@app.get("/datasets/{table}")
def get_dataset(table: str):
    check_table(table)
    return {"table": table, "description": describe_table(table)}


# ---------- Speech to text (part 5) ----------
@app.post("/transcribe")
def speech_to_text(audio: UploadFile, language: Literal["auto", "ar", "en"] = Form("auto")):
    """A recording (wav, mp3, m4a, ogg or webm) -> {"text": ..., "language": ...}"""
    return transcribe_upload(audio, language)


# ---------- SQL (parts 2 and 3) ----------
@app.post("/sql/generate")
def sql_from_question(request: QuestionRequest):
    """A question -> {"sql": ...}. The sql is null when the dataset cannot answer the question."""
    check_table(request.table)
    return {"sql": generate_sql(request.question, request.table)}


@app.post("/sql/execute")
def execute_sql(request: SQLRequest):
    """Run a SELECT query on the datasets (read-only) -> {"columns": [...], "rows": [...], "truncated": ...}"""
    try:
        return run_sql(request.sql)
    except (ValueError, sqlite3.Error) as error:   # refused, too slow, or a mistake in the query
        raise HTTPException(400, str(error))


# ---------- The whole analysis (part 4) ----------
@app.post("/ask")
def ask(request: QuestionRequest):
    """A typed question -> the status, the SQL, the result and an explanation in the language of the question."""
    check_table(request.table)
    return analyze(request.question, request.table)


@app.post("/ask/voice")
def ask_by_voice(audio: UploadFile, table: str = Form(), language: Literal["auto", "ar", "en"] = Form("auto")):
    """A recorded question -> the text Whisper heard, then the same answer as /ask."""
    check_table(table)
    heard = transcribe_upload(audio, language)
    answer = analyze(heard["text"], table)   # the "question" in the answer is the text Whisper heard
    answer["language"] = heard["language"]
    return answer


if __name__ == "__main__":
    import json
    from pathlib import Path

    from fastapi.testclient import TestClient

    # TestClient sends requests to the app directly, without starting the server
    client = TestClient(app)

    def show(name, response):
        text = json.dumps(response.json(), ensure_ascii=False)   # ensure_ascii=False prints Arabic as letters
        print(f"===== {name} -> {response.status_code}")
        print(text[:400])
        print()

    sales = Path("sample_data/sales.csv").read_bytes()
    show("Upload sales.csv", client.post("/datasets", files={"file": ("sales.csv", sales)}))
    show("Upload a .txt file", client.post("/datasets", files={"file": ("notes.txt", b"hello")}))
    show("List the datasets", client.get("/datasets"))
    show("A dataset that does not exist", client.get("/datasets/unknown"))
    show("Run a SELECT", client.post("/sql/execute", json={"sql": "SELECT city, COUNT(*) AS orders FROM sales GROUP BY city"}))
    show("Run a DELETE", client.post("/sql/execute", json={"sql": "DELETE FROM sales"}))
    show("An empty question", client.post("/ask", json={"question": "", "table": "sales"}))

    # These use Gemini (about 5 requests). If Gemini is busy, the answer is the 503 message, not a crash.
    show("Generate SQL", client.post("/sql/generate", json={"question": "How many orders per city?", "table": "sales"}))
    show("Ask by text", client.post("/ask", json={"question": "Which category has the highest sales?", "table": "sales"}))

    # These use the recordings of part 5
    recording = Path("sample_data/question_ar.m4a")
    if recording.exists():
        show("Transcribe", client.post("/transcribe", data={"language": "ar"},
                                       files={"audio": (recording.name, recording.read_bytes())}))
    recording = Path("sample_data/question_en.m4a")
    if recording.exists():
        show("Ask by voice", client.post("/ask/voice", data={"table": "sales", "language": "en"},
                                         files={"audio": (recording.name, recording.read_bytes())}))
