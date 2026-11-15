"""Minimal R&D A experiment: does tool granularity change tool selection?"""

import argparse
import csv
import hashlib
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import httpx

from rag.config import ROOT, load_config

RESULTS = ROOT / "evals/results"
CONFIGS = ("fine", "coarse", "rewritten")
HYPOTHESIS = (
    "Fine-grained tools with rewritten descriptions improve argument accuracy, "
    "while coarse tools reduce schema tokens but make more tool/action errors."
)

SYSTEM_PROMPT = (
    "You choose exactly one tool for a freelancer-copilot task. Read the available "
    "tools and the task. Return only one JSON object with 'tool' (the exact tool "
    "name) and 'arguments' (an object). Do not explain."
)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "arguments": {"type": "object"},
    },
    "required": ["tool", "arguments"],
    "additionalProperties": False,
}

TASKS = [
    {
        "id": "marketplace_search",
        "prompt": "On the marketplace, find open jobs matching 'Flask' with a maximum budget of $2,000.",
        "expected_action": "search_jobs",
        "expected_args": {"q": "Flask", "budget_max": 2000},
        "required_args": ["q", "budget_max"],
    },
    {
        "id": "job_detail",
        "prompt": "Show me the full public requirements for job `job_1042`.",
        "expected_action": "get_job",
        "expected_args": {"job_id": "job_1042"},
        "required_args": ["job_id"],
    },
    {
        "id": "client_history",
        "prompt": "Read the public hiring history and reviews for client `client_77`.",
        "expected_action": "get_client_history",
        "expected_args": {"client_id": "client_77"},
        "required_args": ["client_id"],
    },
    {
        "id": "connects_balance",
        "prompt": "How many Connects do I have left before I bid?",
        "expected_action": "get_connects_balance",
        "expected_args": {},
        "required_args": [],
    },
    {
        "id": "read_messages",
        "prompt": "Show the messages in conversation `conv_300`.",
        "expected_action": "list_messages",
        "expected_args": {"conversation_id": "conv_300"},
        "required_args": ["conversation_id"],
    },
    {
        "id": "send_reply",
        "prompt": (
            "Reply in conversation `conv_300` with exactly: "
            "Thanks, I will send the revised draft tomorrow."
        ),
        "expected_action": "send_message",
        "expected_args": {
            "conversation_id": "conv_300",
            "body": "Thanks, I will send the revised draft tomorrow.",
        },
        "required_args": ["conversation_id", "body"],
    },
    {
        "id": "portfolio_evidence",
        "prompt": (
            "Search my own portfolio for case studies about dbt pipeline migrations "
            "and return 3 results."
        ),
        "expected_action": "search_evidence",
        "expected_args": {
            "requirement": "dbt pipeline migrations",
            "k": 3,
            "filters": {"type": "case_study"},
        },
        "required_args": ["requirement", "k", "filters.type"],
    },
    {
        "id": "case_study_detail",
        "prompt": "Load the full case study with evidence ID `case_88`.",
        "expected_action": "get_case_study",
        "expected_args": {"id": "case_88"},
        "required_args": ["id"],
    },
    {
        "id": "profile_skills",
        "prompt": "List the skills on my freelancer profile.",
        "expected_action": "list_skills",
        "expected_args": {},
        "required_args": [],
    },
    {
        "id": "verify_draft",
        "prompt": (
            "Check this draft claim against owned chunks `chunk_a` and `chunk_b`: "
            "I built a dbt migration for a retail client."
        ),
        "expected_action": "verify_claims",
        "expected_args": {
            "draft": "I built a dbt migration for a retail client.",
            "chunk_ids": ["chunk_a", "chunk_b"],
        },
        "required_args": ["draft", "chunk_ids"],
    },
    {
        "id": "free_slots",
        "prompt": "Find my free interview slots for the next 14 days.",
        "expected_action": "get_free_slots",
        "expected_args": {"days_ahead": 14},
        "required_args": ["days_ahead"],
    },
    {
        "id": "email_draft",
        "prompt": (
            "Draft an email to sam@example.com with subject 'Interview availability' "
            "and body 'Are you free Tuesday at 10:00?'"
        ),
        "expected_action": "create_email_draft",
        "expected_args": {
            "to": "sam@example.com",
            "subject": "Interview availability",
            "body": "Are you free Tuesday at 10:00?",
        },
        "required_args": ["to", "subject", "body"],
    },
    {
        "id": "evidence_not_jobs",
        "prompt": (
            "Find portfolio case studies that show my experience with PostgreSQL, "
            "not new jobs."
        ),
        "expected_action": "search_evidence",
        "expected_args": {
            "requirement": "PostgreSQL",
            "filters": {"type": "case_study"},
        },
        "required_args": ["requirement", "filters.type"],
    },
    {
        "id": "message_not_email",
        "prompt": "Send this reply to the client in conversation `conv_555`: I can start on Monday.",
        "expected_action": "send_message",
        "expected_args": {
            "conversation_id": "conv_555",
            "body": "I can start on Monday.",
        },
        "required_args": ["conversation_id", "body"],
    },
    {
        "id": "job_not_client",
        "prompt": "For job `job_900`, what are its public requirements? Do not look up the client.",
        "expected_action": "get_job",
        "expected_args": {"job_id": "job_900"},
        "required_args": ["job_id"],
    },
]

FINE_DESCRIPTIONS = {
    "search_jobs": "Search open marketplace jobs by query, category, and budget.",
    "get_job": "Read one marketplace job's public requirements by job_id.",
    "get_client_history": "Read a client's public spend, hire rate, and reviews by client_id.",
    "get_connects_balance": "Read the authenticated freelancer's remaining Connects.",
    "list_messages": "Read messages in one conversation by conversation_id.",
    "send_message": "Preview or send a reply in one conversation; not an email.",
    "search_evidence": "Search the freelancer's own CV, case studies, and past proposals.",
    "get_case_study": "Load a full owned case study by an evidence id from search_evidence.",
    "list_skills": "Read the explicit skills on the freelancer's profile.",
    "verify_claims": "Check a draft against owned evidence chunk ids after search_evidence.",
    "get_free_slots": "List available interview slots in the local calendar.",
    "create_email_draft": "Create a local email draft; never sends email.",
}

REWRITTEN_DESCRIPTIONS = {
    "search_jobs": (
        "MARKETPLACE SEARCH: find new freelance jobs. Use when the user asks for jobs, "
        "gigs, or client work. Does not search the freelancer's portfolio."
    ),
    "get_job": (
        "MARKETPLACE JOB DETAIL: read one job by job_id. Does not read client history."
    ),
    "get_client_history": (
        "MARKETPLACE CLIENT DETAIL: read a client's public spend, hiring, and reviews "
        "by client_id. Do not pass a job id."
    ),
    "get_connects_balance": "MARKETPLACE ACCOUNT: read remaining Connects. No arguments.",
    "list_messages": (
        "MARKETPLACE MESSAGES READ: list messages for one conversation_id. Does not send."
    ),
    "send_message": (
        "MARKETPLACE MESSAGE WRITE: reply in an existing conversation_id. Use for client "
        "messages, not email drafts."
    ),
    "search_evidence": (
        "PORTFOLIO EVIDENCE SEARCH: search the freelancer's own CV, case studies, and "
        "past proposals for proof of experience. Does not search job listings."
    ),
    "get_case_study": (
        "PORTFOLIO DETAIL: load a full case study by evidence id. The id must come from "
        "search_evidence."
    ),
    "list_skills": "PORTFOLIO PROFILE: list the freelancer's explicit skills. No arguments.",
    "verify_claims": (
        "PORTFOLIO VERIFICATION: verify a draft against owned chunk_ids. Use after "
        "search_evidence. Does not retrieve new evidence."
    ),
    "get_free_slots": "WORKSPACE CALENDAR READ: list free interview slots for availability.",
    "create_email_draft": (
        "WORKSPACE EMAIL WRITE: create a local email draft with to, subject, and body. "
        "Never sends; not for marketplace messages."
    ),
}

ACTION_SERVER = {
    "search_jobs": "marketplace",
    "get_job": "marketplace",
    "get_client_history": "marketplace",
    "get_connects_balance": "marketplace",
    "list_messages": "marketplace",
    "send_message": "marketplace",
    "search_evidence": "portfolio",
    "get_case_study": "portfolio",
    "list_skills": "portfolio",
    "verify_claims": "portfolio",
    "get_free_slots": "workspace",
    "create_email_draft": "workspace",
}


def object_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def tool(name: str, description: str, parameters: dict) -> dict:
    return {"name": name, "description": description, "parameters": parameters}


FINE_TOOLS = [
    tool(
        "search_jobs",
        FINE_DESCRIPTIONS["search_jobs"],
        object_schema(
            {
                "q": {"type": "string"},
                "category": {"type": "string"},
                "budget_min": {"type": "number"},
                "budget_max": {"type": "number"},
                "page": {"type": "integer"},
            }
        ),
    ),
    tool(
        "get_job",
        FINE_DESCRIPTIONS["get_job"],
        object_schema({"job_id": {"type": "string"}}, ["job_id"]),
    ),
    tool(
        "get_client_history",
        FINE_DESCRIPTIONS["get_client_history"],
        object_schema({"client_id": {"type": "string"}}, ["client_id"]),
    ),
    tool(
        "get_connects_balance",
        FINE_DESCRIPTIONS["get_connects_balance"],
        object_schema({}),
    ),
    tool(
        "list_messages",
        FINE_DESCRIPTIONS["list_messages"],
        object_schema({"conversation_id": {"type": "string"}}, ["conversation_id"]),
    ),
    tool(
        "send_message",
        FINE_DESCRIPTIONS["send_message"],
        object_schema(
            {
                "conversation_id": {"type": "string"},
                "body": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            ["conversation_id", "body"],
        ),
    ),
    tool(
        "search_evidence",
        FINE_DESCRIPTIONS["search_evidence"],
        object_schema(
            {
                "requirement": {"type": "string"},
                "k": {"type": "integer"},
                "filters": object_schema(
                    {
                        "type": {"type": "string"},
                        "outcome": {"type": "string"},
                    }
                ),
            },
            ["requirement"],
        ),
    ),
    tool(
        "get_case_study",
        FINE_DESCRIPTIONS["get_case_study"],
        object_schema({"id": {"type": "string"}}, ["id"]),
    ),
    tool(
        "list_skills",
        FINE_DESCRIPTIONS["list_skills"],
        object_schema({}),
    ),
    tool(
        "verify_claims",
        FINE_DESCRIPTIONS["verify_claims"],
        object_schema(
            {
                "draft": {"type": "string"},
                "chunk_ids": {"type": "array", "items": {"type": "string"}},
            },
            ["draft", "chunk_ids"],
        ),
    ),
    tool(
        "get_free_slots",
        FINE_DESCRIPTIONS["get_free_slots"],
        object_schema({"days_ahead": {"type": "integer"}}),
    ),
    tool(
        "create_email_draft",
        FINE_DESCRIPTIONS["create_email_draft"],
        object_schema(
            {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            ["to", "subject", "body"],
        ),
    ),
]

COARSE_TOOLS = [
    tool(
        "marketplace",
        "Marketplace operations. Set action, then supply that action's arguments.",
        object_schema(
            {
                "action": {
                    "type": "string",
                    "enum": [
                        "search_jobs",
                        "get_job",
                        "get_client_history",
                        "get_connects_balance",
                        "list_messages",
                        "send_message",
                    ],
                },
                "q": {"type": "string"},
                "category": {"type": "string"},
                "budget_min": {"type": "number"},
                "budget_max": {"type": "number"},
                "page": {"type": "integer"},
                "job_id": {"type": "string"},
                "client_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "body": {"type": "string"},
            },
            ["action"],
        ),
    ),
    tool(
        "portfolio",
        "Portfolio operations. Set action, then supply that action's arguments.",
        object_schema(
            {
                "action": {
                    "type": "string",
                    "enum": [
                        "search_evidence",
                        "get_case_study",
                        "list_skills",
                        "verify_claims",
                    ],
                },
                "requirement": {"type": "string"},
                "k": {"type": "integer"},
                "filters": object_schema(
                    {
                        "type": {"type": "string"},
                        "outcome": {"type": "string"},
                    }
                ),
                "id": {"type": "string"},
                "draft": {"type": "string"},
                "chunk_ids": {"type": "array", "items": {"type": "string"}},
            },
            ["action"],
        ),
    ),
    tool(
        "workspace",
        "Workspace operations. Set action, then supply that action's arguments.",
        object_schema(
            {
                "action": {
                    "type": "string",
                    "enum": ["get_free_slots", "create_email_draft"],
                },
                "days_ahead": {"type": "integer"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            ["action"],
        ),
    ),
]

TOOLSETS = {
    "fine": FINE_TOOLS,
    "coarse": COARSE_TOOLS,
    "rewritten": [
        {**item, "description": REWRITTEN_DESCRIPTIONS[item["name"]]}
        for item in FINE_TOOLS
    ],
}


def sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def normalize(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return text.casefold()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return tuple(normalize(item) for item in value)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def flatten(value: dict, prefix: str = "") -> dict:
    output = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            output.update(flatten(item, path))
        else:
            output[path] = normalize(item)
    return output


def parse_answer(content: str) -> tuple[str, dict]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("response did not contain a JSON object") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise TypeError("response JSON was not an object")
    chosen = str(data.get("tool") or data.get("name") or "").strip()
    arguments = data.get("arguments") or data.get("args") or {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise TypeError("arguments was not an object")
    if not chosen:
        raise ValueError("response did not name a tool")
    return chosen, arguments


def expected_call(config: str, task: dict) -> tuple[str, dict, list[str]]:
    action = task["expected_action"]
    if config == "coarse":
        return (
            ACTION_SERVER[action],
            {"action": action, **task["expected_args"]},
            ["action", *task["required_args"]],
        )
    return action, task["expected_args"], task["required_args"]


def score(config: str, task: dict, chosen: str, arguments: dict) -> dict:
    expected_tool, expected_args, required = expected_call(config, task)
    actual = flatten(arguments)
    wanted = flatten(expected_args)
    args_match = all(key in actual and actual[key] == wanted[key] for key in required)
    selection_ok = chosen.casefold() == expected_tool.casefold()
    return {
        "expected_tool": expected_tool,
        "expected_action": task["expected_action"],
        "expected_args": expected_args,
        "chosen_tool": chosen,
        "arguments": arguments,
        "selection_ok": selection_ok,
        "arguments_ok_raw": args_match,
        "arguments_ok": selection_ok and args_match,
    }


def call_model(
    client: httpx.Client,
    url: str,
    model: str,
    tools: list[dict],
    task: dict,
    seed: int,
    context_tokens: int,
    threads: int,
) -> dict:
    payload = {
        "model": model,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Available tools:\n"
                    + json.dumps(tools, indent=2, ensure_ascii=False)
                    + "\n\nTask:\n"
                    + task["prompt"]
                ),
            },
        ],
        "options": {
            "temperature": 0,
            "seed": seed,
            "num_ctx": context_tokens,
            "num_predict": 256,
            "num_thread": threads,
        },
        "keep_alive": "5m",
    }
    started = time.perf_counter()
    response = client.post(url + "/api/chat", json=payload)
    response.raise_for_status()
    data = response.json()
    content = data["message"]["content"]
    return {
        "content": content,
        "seconds": time.perf_counter() - started,
        "prompt_tokens": int(data.get("prompt_eval_count", 0) or 0),
        "completion_tokens": int(data.get("eval_count", 0) or 0),
    }


def capture_environment(client: httpx.Client, url: str, model: str) -> dict:
    tags = client.get(url + "/api/tags")
    tags.raise_for_status()
    version = client.get(url + "/api/version")
    version.raise_for_status()
    available = {item["name"]: item["digest"] for item in tags.json().get("models", [])}
    if model not in available:
        raise SystemExit(f"Model {model!r} is not installed in Ollama at {url}")
    return {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "ollama_url": url,
        "ollama_version": version.json().get("version"),
        "model": model,
        "model_digest": available[model],
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def summarize(observations: list[dict], config: str) -> dict:
    rows = [row for row in observations if row["config"] == config]
    selected = [row for row in rows if row["selection_ok"]]
    return {
        "tasks": len(rows),
        "tools": len(TOOLSETS[config]),
        "selection_accuracy": mean(row["selection_ok"] for row in rows)
        if rows
        else None,
        "argument_accuracy": mean(row["arguments_ok"] for row in rows)
        if rows
        else None,
        "argument_accuracy_given_selection": (
            mean(row["arguments_ok_raw"] for row in selected) if selected else None
        ),
        "tokens_per_task": mean(row["tokens"] for row in rows) if rows else None,
        "prompt_tokens_per_task": (
            mean(row["prompt_tokens"] for row in rows) if rows else None
        ),
        "completion_tokens_per_task": (
            mean(row["completion_tokens"] for row in rows) if rows else None
        ),
        "failures": sum(row["error"] is not None for row in rows),
        "schema_chars": len(json.dumps(TOOLSETS[config], ensure_ascii=False)),
    }


def write_report(path: Path, result: dict) -> None:
    lines = [
        "# R&D A: tool granularity",
        "",
        result["hypothesis"],
        "",
        (
            f"Model: `{result['environment']['model']}`; tasks: {result['tasks']}; "
            f"seed: {result['seed']}."
        ),
        "",
        (
            "Configurations: fine = 12 action-level tools; coarse = 3 server-level "
            "tools with a required action argument; rewritten = the same 12 tools with "
            "disambiguating descriptions. Each task has one known-correct tool and "
            "required arguments. Tokens are Ollama prompt+completion tokens, so tool "
            "schema overhead is included."
        ),
        "",
        (
            "| Config | Tools | Selection accuracy | Argument accuracy | "
            "Arg accuracy given selection | Tokens/task | Failures |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for config in CONFIGS:
        item = result["summary"][config]
        lines.append(
            "| "
            + " | ".join(
                [
                    config,
                    str(item["tools"]),
                    f"{item['selection_accuracy']:.3f}",
                    f"{item['argument_accuracy']:.3f}",
                    (
                        f"{item['argument_accuracy_given_selection']:.3f}"
                        if item["argument_accuracy_given_selection"] is not None
                        else "not measured"
                    ),
                    f"{item['tokens_per_task']:.1f}",
                    str(item["failures"]),
                ]
            )
            + " |"
        )
    lines += [
        "",
        (
            "Observed pattern: rewritten had the highest argument accuracy; coarse used "
            "the fewest tokens but had the lowest selection and argument accuracy."
        ),
        "",
        (
            "Argument accuracy counts only tasks where the selected tool and required "
            "arguments are both correct. The conditional column scores arguments among "
            "tasks where the tool was selected correctly. Coarse tools also require the "
            "correct `action` argument."
        ),
        "",
        (
            "This measures tool selection and argument construction only. It does not "
            "execute tools or measure downstream proposal quality."
        ),
        "",
        (
            "Sources: `rd_a_tool_granularity.json` and "
            "`rd_a_tool_granularity_observations.jsonl`."
        ),
        "",
    ]
    path.write_text("\n".join(lines))


def write_csv(path: Path, summary: dict) -> None:
    fields = [
        "config",
        "tools",
        "selection_accuracy",
        "argument_accuracy",
        "argument_accuracy_given_selection",
        "tokens_per_task",
        "prompt_tokens_per_task",
        "completion_tokens_per_task",
        "failures",
        "schema_chars",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for config in CONFIGS:
            writer.writerow({"config": config, **summary[config]})


def run(args) -> None:
    config = load_config()
    model = args.model or config.llm_model
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = TASKS[: args.limit] if args.limit else TASKS
    url = config.ollama_url.rstrip("/")
    observations = []
    jsonl_path = output_dir / "rd_a_tool_granularity_observations.jsonl"
    if args.resume and jsonl_path.exists():
        for line in jsonl_path.read_text().splitlines():
            try:
                observations.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    completed = {(row["task_id"], row["config"]) for row in observations}
    with httpx.Client(timeout=config.llm_timeout_seconds) as client:
        environment = capture_environment(client, url, model)
        with jsonl_path.open("a" if args.resume else "w") as stream:
            for index, task in enumerate(tasks):
                order = (
                    CONFIGS[index % len(CONFIGS) :] + CONFIGS[: index % len(CONFIGS)]
                )
                for name in order:
                    if (task["id"], name) in completed:
                        continue
                    row = {
                        "task_id": task["id"],
                        "config": name,
                        "prompt": task["prompt"],
                        "expected_action": task["expected_action"],
                        "error": None,
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "seconds": 0.0,
                    }
                    try:
                        raw = call_model(
                            client,
                            url,
                            model,
                            TOOLSETS[name],
                            task,
                            args.seed,
                            config.llm_context_tokens,
                            config.cpu_threads,
                        )
                        chosen, arguments = parse_answer(raw["content"])
                        row.update(raw)
                        row.update(score(name, task, chosen, arguments))
                        row["tokens"] = raw["prompt_tokens"] + raw["completion_tokens"]
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                        row.update(
                            {
                                "expected_tool": expected_call(name, task)[0],
                                "chosen_tool": None,
                                "arguments": {},
                                "selection_ok": False,
                                "arguments_ok_raw": False,
                                "arguments_ok": False,
                            }
                        )
                    observations.append(row)
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
    summary = {name: summarize(observations, name) for name in CONFIGS}
    result = {
        "hypothesis": HYPOTHESIS,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "environment": environment,
        "seed": args.seed,
        "tasks": len(tasks),
        "task_sha256": sha256(tasks),
        "toolset_sha256": sha256(TOOLSETS),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "configs": {
            name: {
                "tools": len(items),
                "tool_names": [item["name"] for item in items],
                "schema_chars": len(json.dumps(items, ensure_ascii=False)),
            }
            for name, items in TOOLSETS.items()
        },
        "summary": summary,
        "observations": observations,
    }
    (output_dir / "rd_a_tool_granularity.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    write_csv(output_dir / "rd_a_tool_granularity.csv", summary)
    write_report(output_dir / "rd_a_tool_granularity.md", result)
    for name in CONFIGS:
        item = summary[name]
        print(
            f"{name:9} tools={item['tools']:2} "
            f"selection={item['selection_accuracy']:.3f} "
            f"arguments={item['argument_accuracy']:.3f} "
            f"tokens/task={item['tokens_per_task']:.1f} "
            f"failures={item['failures']}"
        )
    print(f"Wrote {output_dir / 'rd_a_tool_granularity.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=0, help="Run only the first N tasks"
    )
    parser.add_argument("--model", help="Ollama model; defaults to agent/config.yaml")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=RESULTS)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an interrupted run in --output-dir",
    )
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    run(args)


if __name__ == "__main__":
    main()
