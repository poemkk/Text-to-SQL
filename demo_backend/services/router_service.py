FRAMEWORK_STEPS = [
    {"id": 1, "name": "Input Task"},
    {"id": 2, "name": "Task Routing"},
    {"id": 3, "name": "Context Building"},
    {"id": 4, "name": "Candidate Generation"},
    {"id": 5, "name": "Validation Environment"},
    {"id": 6, "name": "Error-feedback Repair"},
    {"id": 7, "name": "Re-validation / Re-testing"},
    {"id": 8, "name": "Final Selection"},
    {"id": 9, "name": "Metrics Evaluation"},
]


def get_framework():
    return {
        "title": "A²V Framework for LLM-generated executable tasks",
        "steps": FRAMEWORK_STEPS,
        "supported_tasks": {
            "sql": "SQLite / DuckDB / PostgreSQL / MySQL execution validation",
            "python": "unit-test validation",
            "java": "javac compilation + test validation",
        },
    }


def route_task(task_type: str, question: str):
    routes = {
        "sql": {
            "route": "Text-to-SQL pipeline",
            "validation_environment": "SQLite execution",
            "context_type": "database schema",
        },
        "python": {
            "route": "Python code-generation pipeline",
            "validation_environment": "unit tests",
            "context_type": "programming task prompt",
        },
        "java": {
            "route": "Java code-generation pipeline",
            "validation_environment": "javac + tests",
            "context_type": "method signature and test harness",
        },
    }
    if task_type not in routes:
        raise ValueError(f"Unsupported task_type: {task_type}")
    return {"task_type": task_type, **routes[task_type]}
