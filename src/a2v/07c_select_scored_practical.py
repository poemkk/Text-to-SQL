import argparse
import json
import re
from collections import Counter
from pathlib import Path


SOURCE_SCORE = {
    "embedrag": 5.0,
    "bm25rag": 4.0,
    "lora_rag": 3.0,
    "promptonly": 1.0,
    "loraonly_ep3": 0.5,
}

SOURCE_TIE_RANK = {
    "embedrag": 0,
    "bm25rag": 1,
    "lora_rag": 2,
    "promptonly": 3,
    "loraonly_ep3": 4,
}

VARIANT_TIE_RANK = {
    "original": 0,
    "strong_repair": 1,
}


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path, rows):
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_result_key(result):
    if result is None:
        return "NULL_RESULT"

    normalized_rows = []
    for row in result:
        if isinstance(row, (list, tuple)):
            normalized_rows.append(tuple(normalize_cell(cell) for cell in row))
        else:
            normalized_rows.append((normalize_cell(row),))

    return json.dumps(sorted(normalized_rows), ensure_ascii=False, sort_keys=True)


def normalize_cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def is_empty_result(result):
    return result is None or result == []


def normalize_sql(sql):
    if not sql:
        return ""
    sql = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"\s+", " ", sql).strip().lower()


def word_count(text):
    return len(re.findall(r"[a-z0-9_']+", (text or "").lower()))


def has_word(text, words):
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def has_phrase(text, phrase):
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def has_function(sql, name):
    return re.search(rf"\b{re.escape(name.lower())}\s*\(", sql) is not None


def has_order_limit(sql, direction):
    return (
        re.search(r"\border\s+by\b", sql) is not None
        and re.search(rf"\b{direction}\b", sql) is not None
        and re.search(r"\blimit\b", sql) is not None
    )


def select_clause(sql):
    match = re.search(r"\bselect\b\s+(.*?)\s+\bfrom\b", sql, flags=re.DOTALL)
    return match.group(1) if match else ""


def group_by_clause(sql):
    match = re.search(
        r"\bgroup\s+by\b\s+(.*?)(?:\border\s+by\b|\bhaving\b|\blimit\b|;|$)",
        sql,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def has_bad_spaced_literal(sql):
    for match in re.finditer(r"'([^']*)'", sql):
        literal = match.group(1)
        if literal != literal.strip():
            return True
    return False


def question_features(question):
    q = (question or "").lower()
    has_each_or_per = has_word(q, ["each", "per"])
    has_by = has_word(q, ["by"]) and re.search(
        r"\b(?:not\s+used|used|written|composed|sung|performed|owned|created)\s+by\b",
        q,
    ) is None
    group_strength = 1.5 if has_each_or_per else (0.75 if has_by else 0.0)
    number_as_count = has_word(q, ["number"]) and not re.search(
        r"\bnumber\s+of\s+(years?|times?)\b",
        q,
    )
    superlative_ranking = has_word(q, ["most", "greatest", "largest"])
    average_entity_filter = re.search(
        r"\b(who|that|which)\s+have\b|\bgone\s+through\b|\bany\s+(friends?|treatments?)\b",
        q,
    ) is not None
    return {
        "text": q,
        "count": has_phrase(q, "how many")
        or has_word(q, ["count"])
        or number_as_count,
        "average": has_word(q, ["average", "avg", "mean"]),
        "maximum": has_word(q, ["maximum", "max", "highest", "oldest"])
        or superlative_ranking,
        "minimum": has_word(q, ["minimum", "min", "lowest", "youngest"]),
        "oldest": has_word(q, ["oldest"]),
        "youngest": has_word(q, ["youngest"]),
        "superlative_ranking": superlative_ranking,
        "not_used": re.search(r"\bnot\s+used\b", q) is not None,
        "us_territory": "us territory" in q,
        "enrollment_id": re.search(r"\benrollment\s+id\b", q) is not None,
        "count_distinct_entity": re.search(
            r"\bwho\s+participated\b|\bnumber\s+of\b.*\b(winners?|players?|students?|people|owners?)\b.*\bwho\b",
            q,
        ) is not None,
        "average_entity_filter": average_entity_filter,
        "language_use_without_official": (
            has_word(q, ["use", "uses", "speak", "speaks", "spoken"])
            and "official" not in q
        ),
        "group": group_strength > 0.0,
        "group_strength": group_strength,
        "each_or_per": has_each_or_per,
        "order": has_word(q, ["order", "ordered", "sort", "sorted"]),
        "word_count": word_count(q),
    }


def sql_features(sql_text):
    sql = normalize_sql(sql_text)
    selected = select_clause(sql)
    grouped = group_by_clause(sql)
    return {
        "text": sql,
        "token_count": word_count(sql),
        "select_clause": selected,
        "group_by_clause": grouped,
        "has_count": has_function(sql, "count"),
        "has_count_star": re.search(r"\bcount\s*\(\s*\*\s*\)", sql) is not None,
        "has_count_distinct": re.search(r"\bcount\s*\(\s*distinct\b", sql) is not None,
        "select_has_count": has_function(selected, "count"),
        "has_avg": has_function(sql, "avg"),
        "has_max": has_function(sql, "max"),
        "has_min": has_function(sql, "min"),
        "has_group_by": re.search(r"\bgroup\s+by\b", sql) is not None,
        "has_order_by": re.search(r"\border\s+by\b", sql) is not None,
        "has_join": re.search(r"\bjoin\b", sql) is not None,
        "has_left_join": re.search(r"\bleft\s+(?:outer\s+)?join\b", sql) is not None,
        "has_limit": re.search(r"\blimit\b", sql) is not None,
        "has_desc_limit": has_order_limit(sql, "desc"),
        "has_asc_limit": has_order_limit(sql, "asc"),
        "has_date_order_hint": re.search(r"(date|year|birth|born)", sql) is not None,
        "has_bad_spaced_literal": has_bad_spaced_literal(sql),
        "has_not_in_or_exists": re.search(r"\bnot\s+in\s*\(|\bnot\s+exists\b", sql) is not None,
        "has_left_join_is_null": (
            re.search(r"\bleft\s+(?:outer\s+)?join\b", sql) is not None
            and re.search(r"\bis\s+null\b", sql) is not None
        ),
        "has_in_or_exists_or_distinct": re.search(r"\bin\s*\(|\bexists\b|\bdistinct\b", sql) is not None,
        "has_isofficial": "isofficial" in sql,
        "has_governmentform": "governmentform" in sql,
        "has_enrollment": "enrollment" in sql,
        "group_by_has_id": re.search(r"\b\w*id\b", grouped) is not None,
    }


def add(breakdown, rule, delta, detail):
    breakdown.append({
        "rule": rule,
        "delta": round(delta, 4),
        "detail": detail,
    })
    return delta


def build_pool(candidates):
    pool = []

    for idx, cand in enumerate(candidates):
        source = cand.get("source")
        repair_attempted = bool(cand.get("strong_repair_attempted"))
        repair_sql = cand.get("strong_repair_final_sql")
        repair_exec_ok = bool(cand.get("strong_repair_exec_ok"))

        pool.append({
            "candidate_index": idx,
            "source": source,
            "variant": "original",
            "sql": cand.get("sql"),
            "exec_ok": bool(cand.get("exec_ok")),
            "exec_error": cand.get("exec_error"),
            "result": cand.get("result"),
            "result_key": cand.get("result_key")
            or normalize_result_key(cand.get("result")),
            "strong_repair_attempted": repair_attempted,
            "original_exec_ok": bool(cand.get("exec_ok")),
            "repair_exec_ok": repair_exec_ok,
            "repair_available": repair_attempted and bool(repair_sql),
            "order": len(pool),
        })

        if repair_attempted or repair_sql:
            pool.append({
                "candidate_index": idx,
                "source": source,
                "variant": "strong_repair",
                "sql": repair_sql,
                "exec_ok": repair_exec_ok,
                "exec_error": cand.get("strong_repair_exec_error"),
                "result": cand.get("strong_repair_result"),
                "result_key": cand.get("strong_repair_result_key")
                or normalize_result_key(cand.get("strong_repair_result")),
                "strong_repair_attempted": repair_attempted,
                "original_exec_ok": bool(cand.get("exec_ok")),
                "repair_exec_ok": repair_exec_ok,
                "repair_available": bool(repair_sql),
                "order": len(pool),
            })

    return pool


def score_candidate(candidate, q_features, consistency_counts):
    breakdown = []
    score = 0.0
    sql = sql_features(candidate.get("sql"))
    source = candidate.get("source")
    variant = candidate.get("variant")
    exec_ok = bool(candidate.get("exec_ok"))

    if exec_ok:
        score += add(breakdown, "execution", 10.0, "SQL executed successfully")
    else:
        score += add(breakdown, "execution", -10.0, "SQL did not execute")

    source_delta = SOURCE_SCORE.get(source, 0.0)
    score += add(
        breakdown,
        "source_reliability",
        source_delta,
        f"historical source score for {source}",
    )

    if variant == "strong_repair":
        if exec_ok and not candidate.get("original_exec_ok"):
            score += add(
                breakdown,
                "repair_variant",
                1.0,
                "repair is executable while original was not",
            )
        elif exec_ok:
            score += add(
                breakdown,
                "repair_variant",
                0.25,
                "repair is executable, with original also executable",
            )
        else:
            score += add(
                breakdown,
                "repair_variant",
                -2.0,
                "repair variant is still not executable",
            )

        if sql["has_bad_spaced_literal"]:
            score += add(
                breakdown,
                "repair_spaced_literal",
                -2.0,
                "repair SQL has string literals with leading or trailing spaces",
            )
    elif (
        exec_ok
        and candidate.get("repair_available")
        and candidate.get("repair_exec_ok")
    ):
        score += add(
            breakdown,
            "repair_guard",
            0.25,
            "original is executable, so do not prefer repair solely for being executable",
        )

    if q_features["count"]:
        if sql["has_count"]:
            score += add(breakdown, "keyword_count", 2.0, "count question has COUNT")
        else:
            score += add(breakdown, "keyword_count", -3.0, "count question lacks COUNT")

    if q_features["average"]:
        if sql["has_avg"]:
            score += add(breakdown, "keyword_average", 2.0, "average question has AVG")
        else:
            score += add(breakdown, "keyword_average", -2.5, "average question lacks AVG")

    if q_features["maximum"]:
        oldest_date_order = (
            q_features["oldest"]
            and sql["has_asc_limit"]
            and sql["has_date_order_hint"]
        )
        if sql["has_max"] or sql["has_desc_limit"] or oldest_date_order:
            score += add(
                breakdown,
                "keyword_maximum",
                2.0,
                "maximum-style question has MAX or ORDER BY DESC LIMIT",
            )
        else:
            score += add(
                breakdown,
                "keyword_maximum",
                -2.5,
                "maximum-style question lacks MAX or ORDER BY DESC LIMIT",
            )

    if q_features["minimum"]:
        youngest_date_order = (
            q_features["youngest"]
            and sql["has_desc_limit"]
            and sql["has_date_order_hint"]
        )
        if sql["has_min"] or sql["has_asc_limit"] or youngest_date_order:
            score += add(
                breakdown,
                "keyword_minimum",
                2.0,
                "minimum-style question has MIN or ORDER BY ASC LIMIT",
            )
        else:
            score += add(
                breakdown,
                "keyword_minimum",
                -2.5,
                "minimum-style question lacks MIN or ORDER BY ASC LIMIT",
            )

    if q_features["group"]:
        if sql["has_group_by"]:
            score += add(
                breakdown,
                "keyword_group",
                q_features["group_strength"],
                "group-style question has GROUP BY",
            )
        else:
            score += add(
                breakdown,
                "keyword_group",
                -q_features["group_strength"],
                "group-style question lacks GROUP BY",
            )

    if q_features["count"] and q_features["each_or_per"] and sql["has_count"]:
        if sql["has_left_join"]:
            score += add(
                breakdown,
                "count_each_left_join",
                0.75,
                "per-item count query uses LEFT JOIN to preserve zero-count groups",
            )
        elif sql["has_join"] and sql["has_group_by"]:
            score += add(
                breakdown,
                "count_each_inner_join",
                -0.5,
                "per-item count query uses an inner join, which may drop zero-count groups",
            )

    if q_features["order"]:
        if sql["has_order_by"]:
            score += add(breakdown, "keyword_order", 1.5, "ordering question has ORDER BY")
        else:
            score += add(breakdown, "keyword_order", -1.5, "ordering question lacks ORDER BY")

    ranking_count_only_for_sort = (
        q_features["superlative_ranking"]
        and sql["select_has_count"]
        and "," in sql["select_clause"]
        and not re.search(
            r"\b(and|with)\s+(the\s+)?(number|count|total)\b",
            q_features["text"],
        )
    )
    if ranking_count_only_for_sort:
        score += add(
            breakdown,
            "mismatch_ranking_outputs_count",
            -2.0,
            "superlative ranking query selects COUNT as an extra output column",
        )

    if (
        q_features["superlative_ranking"]
        and sql["has_count"]
        and sql["has_group_by"]
        and sql["has_desc_limit"]
    ):
        if sql["group_by_has_id"]:
            score += add(
                breakdown,
                "ranking_group_by_id",
                0.75,
                "superlative count ranking groups by an id-like key",
            )
        elif re.search(r"\bname\b", sql["group_by_clause"]):
            score += add(
                breakdown,
                "ranking_group_by_name",
                -0.75,
                "superlative count ranking groups by name-like fields instead of an id-like key",
            )

    if q_features["not_used"]:
        if sql["has_not_in_or_exists"]:
            score += add(
                breakdown,
                "not_used_antijoin",
                1.0,
                "not-used question uses NOT IN or NOT EXISTS",
            )
        elif sql["has_left_join_is_null"]:
            score += add(
                breakdown,
                "not_used_left_join_null",
                -0.5,
                "not-used question uses LEFT JOIN IS NULL, which is more fragile here",
            )

    if q_features["us_territory"] and not sql["has_governmentform"]:
        score += add(
            breakdown,
            "mismatch_us_territory_column",
            -2.0,
            "US territory question does not filter the government-form column",
        )

    if q_features["enrollment_id"] and not sql["has_enrollment"]:
        score += add(
            breakdown,
            "mismatch_enrollment_id_column",
            -2.0,
            "question asks for enrollment id but SQL does not reference enrollment",
        )

    if (
        q_features["count_distinct_entity"]
        and sql["has_count_star"]
        and not sql["has_count_distinct"]
    ):
        score += add(
            breakdown,
            "mismatch_entity_count_distinct",
            -1.25,
            "entity-count question uses COUNT(*) instead of COUNT(DISTINCT ...)",
        )

    if (
        q_features["average_entity_filter"]
        and sql["has_avg"]
        and sql["has_join"]
        and not sql["has_in_or_exists_or_distinct"]
    ):
        score += add(
            breakdown,
            "mismatch_avg_join_duplicates",
            -2.0,
            "average over filtered entities uses a direct JOIN that may duplicate entities",
        )

    if q_features["language_use_without_official"] and sql["has_isofficial"]:
        score += add(
            breakdown,
            "mismatch_unasked_official_filter",
            -2.0,
            "language-use question adds an official-language filter not requested",
        )

    if q_features["count"] and not sql["has_count"]:
        select_text = sql["select_clause"]
        if re.search(r"\b(name|text|title|first_name|last_name|fname|lname)\b", select_text):
            score += add(
                breakdown,
                "mismatch_count_select_text",
                -2.0,
                "count question selects text/name-like fields instead of COUNT",
            )

    simple_count_question = (
        q_features["count"]
        and not q_features["group"]
        and q_features["word_count"] <= 12
    )
    if (
        simple_count_question
        and sql["has_join"]
        and sql["has_group_by"]
        and sql["has_order_by"]
        and sql["has_limit"]
    ):
        score += add(
            breakdown,
            "mismatch_simple_count_complex_sql",
            -2.0,
            "simple count question has JOIN + GROUP BY + ORDER BY + LIMIT",
        )

    if q_features["word_count"] <= 8 and sql["token_count"] >= 80:
        score += add(
            breakdown,
            "mismatch_long_sql_short_question",
            -1.0,
            "SQL is very long for a short question",
        )
    elif q_features["word_count"] <= 8 and sql["token_count"] >= 50:
        score += add(
            breakdown,
            "mismatch_long_sql_short_question",
            -0.5,
            "SQL is somewhat long for a short question",
        )

    if exec_ok and is_empty_result(candidate.get("result")):
        score += add(breakdown, "empty_result", -0.5, "executable SQL returned an empty result")

    if exec_ok:
        same_result_count = consistency_counts.get(candidate.get("result_key"), 0)
        if same_result_count > 1:
            delta = min(2.0, 0.5 * (same_result_count - 1))
            score += add(
                breakdown,
                "result_consistency",
                delta,
                f"result_key shared by {same_result_count} executable candidates",
            )

    return round(score, 4), breakdown


def score_pool(pool, question):
    consistency_counts = Counter(
        cand.get("result_key")
        for cand in pool
        if cand.get("exec_ok") and cand.get("result_key") != "NULL_RESULT"
    )
    q_features = question_features(question)

    scored = []
    for candidate in pool:
        score, breakdown = score_candidate(candidate, q_features, consistency_counts)
        scored_candidate = dict(candidate)
        scored_candidate["score"] = score
        scored_candidate["score_breakdown"] = breakdown
        scored.append(scored_candidate)
    return scored


def select_scored_candidate(pool, question):
    scored = score_pool(pool, question)
    return sorted(
        scored,
        key=lambda cand: (
            -cand["score"],
            SOURCE_TIE_RANK.get(cand.get("source"), 999),
            VARIANT_TIE_RANK.get(cand.get("variant"), 999),
            cand.get("order", 999999),
        ),
    )[0]


def selected_exec_correct(item, selected):
    cand = item["candidates"][selected["candidate_index"]]
    if selected.get("variant") == "strong_repair":
        return bool(cand.get("strong_repair_exec_correct"))
    return bool(cand.get("exec_correct"))


def make_output_record(item, selected):
    return {
        "idx": item.get("idx"),
        "db_id": item.get("db_id"),
        "question": item.get("question"),
        "gold": item.get("gold"),
        "selected_source": selected.get("source"),
        "selected_variant": selected.get("variant"),
        "selected_sql": selected.get("sql"),
        "selected_exec_ok": bool(selected.get("exec_ok")),
        "selected_exec_error": selected.get("exec_error"),
        "selected_result": selected.get("result"),
        "selected_exec_correct": selected_exec_correct(item, selected),
        "score": selected.get("score"),
        "score_breakdown": selected.get("score_breakdown"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        "--in_file",
        dest="input",
        default="runs/outputs/a2v/repaired_strong_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--out",
        default="runs/outputs/a2v/selected_after_strong_repair_scored_v3_spider1034_full.jsonl",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    output_rows = []

    for item in rows:
        pool = build_pool(item.get("candidates", []))
        selected = select_scored_candidate(pool, item.get("question", ""))
        output_rows.append(make_output_record(item, selected))

    write_jsonl(args.out, output_rows)

    total = len(output_rows)
    exec_ok = sum(1 for row in output_rows if row.get("selected_exec_ok"))
    correct = sum(1 for row in output_rows if row.get("selected_exec_correct"))
    print("=== Scored Practical Strong Repair Selector v3 ===")
    print(f"examples: {total}")
    print(f"selected_exec_rate: {exec_ok / total:.4f}" if total else "selected_exec_rate: 0.0000")
    print(
        f"selected_execution_accuracy: {correct / total:.4f}"
        if total
        else "selected_execution_accuracy: 0.0000"
    )
    print(f"[OK] output: {args.out}")


if __name__ == "__main__":
    main()
