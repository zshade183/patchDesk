"""Aggregate provider-reported usage from the desktop agent's main requests."""
import json
import statistics


TOKEN_FIELDS = (
    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens",
)


def record_usage(path, response):
    usage = getattr(response, "usage", None)
    counts = {field: getattr(usage, field, None) for field in TOKEN_FIELDS}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(counts) + "\n")


def task_usage(path):
    if not path.is_file():
        return None
    counts = dict.fromkeys(TOKEN_FIELDS, 0)
    measured = 0
    requests = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        requests += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item["input_tokens"] is None or item["output_tokens"] is None:
            continue
        measured += 1
        for field in TOKEN_FIELDS:
            counts[field] += item[field] or 0
    return {
        **(counts if measured else dict.fromkeys(TOKEN_FIELDS)),
        "requests": requests,
        "requests_with_usage": measured,
        "total_tokens": sum(counts.values()) if measured else None,
    }


def benchmark_usage(rows):
    tracked = [row["usage"] for row in rows if row.get("usage") is not None]
    if not tracked:
        return None
    measured = [item for item in tracked if item["total_tokens"] is not None]
    full = [
        item for row in rows
        if (item := row.get("usage")) is not None
        and 0 < item["requests_with_usage"] == item["requests"] == row["turns"]
    ]
    totals = {field: sum(item[field] for item in measured) for field in TOKEN_FIELDS}
    total = sum(totals.values())
    solved = sum(row["solved"] for row in rows)
    return {
        **(totals if measured else dict.fromkeys(TOKEN_FIELDS)),
        "total_tokens": total if measured else None,
        "requests": sum(item["requests"] for item in tracked),
        "requests_with_usage": sum(item["requests_with_usage"] for item in tracked),
        "tasks_with_complete_usage": len(full),
        "median_tokens_per_task": statistics.median(item["total_tokens"] for item in full) if full else None,
        "tokens_per_solved_task": round(total / solved, 2) if solved and len(full) == len(rows) else None,
    }
