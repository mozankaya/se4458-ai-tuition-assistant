"""Tool trace for each interaction: tool names, inputs, results and the final answer."""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ToolTraceEntry:
    step: int
    tool: str
    input: dict[str, Any]
    result: Any
    duration_ms: int
    confirmation: str | None = None  # "yes" / "no" for payment tools


@dataclass
class InteractionTrace:
    question: str
    user: str | None
    student_no: str | None
    llm: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    tool_calls: list[ToolTraceEntry] = field(default_factory=list)
    final_answer: str | None = None
    llm_calls: int = 0
    token_usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    _t0: float = field(default_factory=time.monotonic, repr=False)

    def add_usage(self, usage: dict[str, int]) -> None:
        self.llm_calls += 1
        for key in self.token_usage:
            self.token_usage[key] += usage.get(key, 0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_t0")
        data["duration_ms"] = int((time.monotonic() - self._t0) * 1000)
        return data


def _slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit] or "interaction"


def save_trace(trace: InteractionTrace, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = directory / f"agent_{stamp}_{_slug(trace.question)}.json"
    path.write_text(json.dumps(trace.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def format_trace(trace: InteractionTrace, max_result_chars: int = 300) -> str:
    """Compact console view of the tool trace."""
    lines = [f"--- Tool trace ({len(trace.tool_calls)} tool call(s), {trace.llm_calls} LLM call(s)) ---"]
    for entry in trace.tool_calls:
        result = json.dumps(entry.result, ensure_ascii=False)
        if len(result) > max_result_chars:
            result = result[:max_result_chars] + "..."
        confirmation = f" confirmation={entry.confirmation}" if entry.confirmation else ""
        lines.append(f"[{entry.step}] {entry.tool} input={json.dumps(entry.input)}{confirmation}")
        lines.append(f"    result={result}")
    lines.append("--- end of trace ---")
    return "\n".join(lines)
