from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services import java_service, metrics_service, python_service, router_service, sql_service

app = FastAPI(title="A2V Prototype", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RouteTaskRequest(BaseModel):
    task_type: str
    question: str = ""


class SqlGenerateRequest(BaseModel):
    db_id: str
    question: str
    method: str


class SqlExecuteRequest(BaseModel):
    db_id: str
    sql: str


class SqlRepairRequest(BaseModel):
    db_id: str
    question: str
    bad_sql: str
    error: str = ""


class RepairRequest(BaseModel):
    code: str
    error: str = ""


@app.get("/api/health")
def health():
    return {"ok": True, "system": "A2V Prototype", "tasks": ["sql", "python", "java"]}


@app.get("/api/framework")
def framework():
    return router_service.get_framework()


@app.post("/api/route_task")
def route_task(payload: RouteTaskRequest):
    try:
        return router_service.route_task(payload.task_type, payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sql/databases")
def sql_databases():
    return sql_service.get_databases()


@app.get("/api/sql/examples")
def sql_examples(db_id: str = Query(...)):
    return sql_service.get_examples(db_id)


@app.get("/api/sql/schema")
def sql_schema(db_id: str = Query(...)):
    return sql_service.get_schema(db_id)


@app.post("/api/sql/generate")
def sql_generate(payload: SqlGenerateRequest):
    try:
        return sql_service.generate_sql(payload.db_id, payload.question, payload.method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sql/execute")
def sql_execute(payload: SqlExecuteRequest):
    return sql_service.execute_sql(payload.db_id, payload.sql)


@app.post("/api/sql/repair_demo")
def sql_repair(payload: SqlRepairRequest):
    return sql_service.repair_demo(
        payload.db_id,
        payload.question,
        payload.bad_sql,
        payload.error,
    )


@app.get("/api/python/summary")
def python_summary():
    return python_service.summary()


@app.get("/api/python/examples")
def python_examples():
    return python_service.examples()


@app.post("/api/python/repair_demo")
def python_repair(payload: RepairRequest):
    return python_service.repair_demo(payload.code, payload.error)


@app.get("/api/java/summary")
def java_summary():
    return java_service.summary()


@app.get("/api/java/examples")
def java_examples():
    return java_service.examples()


@app.post("/api/java/repair_demo")
def java_repair(payload: RepairRequest):
    return java_service.repair_demo(payload.code, payload.error)


@app.get("/api/metrics/overview")
def metrics_overview():
    return metrics_service.metrics_overview()
