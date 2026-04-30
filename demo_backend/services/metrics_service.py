def metrics_overview():
    return {
        "sql": [
            {"method": "promptonly", "exec_rate": 0.144, "exec_acc": 0.114},
            {"method": "bm25rag", "exec_rate": 0.940, "exec_acc": 0.642},
            {"method": "embedrag", "exec_rate": 0.980, "exec_acc": 0.734},
            {"method": "rule_selector_priority", "exec_rate": 0.998, "exec_acc": 0.745},
            {
                "method": "A2V_full_strong_repair_practical_v2",
                "exec_rate": 0.998,
                "exec_acc": 0.779,
            },
            {
                "method": "strong_repair_oracle_upper_bound",
                "exec_rate": 0.998,
                "exec_acc": 0.868,
            },
        ],
        "python": {
            "dataset": "APPS-500",
            "best_initial_model": "gemini-3.1-flash-lite-preview",
            "best_initial_pass": 0.708,
            "best_final_model": "gemini-3.1-flash-lite-preview",
            "best_final_pass": 0.912,
        },
        "java": {
            "dataset": "MBPP-Java-386",
            "best_initial_model": "gemini-3.1-flash-lite-preview",
            "best_initial_pass": 0.847,
            "best_final_model": "gemini-3.1-flash-lite-preview",
            "best_final_pass": 0.966,
        },
        "multi_backend": [
            {"backend": "DuckDB", "after_exec": 0.996, "same_result": 0.760},
            {"backend": "PostgreSQL", "after_exec": 0.994, "same_result": 0.755},
            {"backend": "MySQL", "after_exec": 0.998, "same_result": 0.755},
        ],
    }
