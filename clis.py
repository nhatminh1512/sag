"""CLI adapters — how `sag` talks to each agent CLI.

A step config names a CLI (`cli`), optionally a model (`model`), and may override
any part of the invocation (`bin`, `base`, `prompt`, `model_flag`). Known CLIs get
a sensible default here; a custom CLI can be described entirely in the project
config:

    {"cli": "mycli", "bin": "/opt/mycli", "base": ["run", "{prompt}"],
     "prompt": "argv", "model_flag": "--model", "model": "x"}

`base` may contain `{prompt}` (argv mode) and `{permission}`. Model arguments are
appended after the prompt, which keeps flags like grok's `-p <prompt>` intact.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class CliSpec:
    name: str
    base: tuple[str, ...]
    prompt: str = "stdin"              # "stdin" or "argv"
    model: tuple[str, ...] | None = None
    models: tuple[str, ...] = ()
    note: str = ""


# Order matters: it is the order shown by `sag setup`.
REGISTRY: dict[str, CliSpec] = {
    "claude": CliSpec(
        "claude",
        ("-p", "--permission-mode", "{permission}"),
        "stdin",
        ("--model", "{model}"),
        ("opus", "sonnet", "haiku"),
    ),
    "grok": CliSpec(
        "grok",
        ("-p", "{prompt}", "--always-approve"),
        "argv",
        ("-m", "{model}"),
        ("grok-4", "grok-3"),
    ),
    "dsh": CliSpec(
        "dsh",
        ("headless", "-"),
        "stdin",
        None,
        (),
        "model comes from the active dsh profile",
    ),
    "codex": CliSpec(
        "codex",
        ("exec", "--full-auto", "{prompt}"),
        "argv",
        ("-m", "{model}"),
        ("gpt-5", "gpt-5-codex"),
    ),
    "opencode": CliSpec(
        "opencode",
        ("run", "{prompt}"),
        "argv",
        ("-m", "{model}"),
        ("anthropic/claude-sonnet-4-5", "openai/gpt-5", "google/gemini-2.5-pro"),
    ),
    "gemini": CliSpec(
        "gemini",
        ("-p", "{prompt}"),
        "argv",
        ("-m", "{model}"),
        ("gemini-2.5-pro", "gemini-2.5-flash"),
    ),
    "aider": CliSpec(
        "aider",
        ("--message", "{prompt}", "--yes"),
        "argv",
        ("--model", "{model}"),
        ("sonnet", "gpt-5"),
    ),
    "qwen": CliSpec(
        "qwen",
        ("-p", "{prompt}"),
        "argv",
        ("-m", "{model}"),
        ("qwen3-coder-plus",),
    ),
    "cursor-agent": CliSpec(
        "cursor-agent",
        ("-p", "{prompt}"),
        "argv",
        ("--model", "{model}"),
        ("sonnet-4.5", "gpt-5"),
    ),
}


def resolve(name: str) -> CliSpec | None:
    return REGISTRY.get(name)


def detect() -> list[tuple[str, str, CliSpec]]:
    """Every known CLI that is actually on PATH, in registry order."""
    found = []
    for name, spec in REGISTRY.items():
        path = shutil.which(name)
        if path:
            found.append((name, path, spec))
    return found


def build(step: dict, prompt: str, model: str | None = None) -> tuple[list[str], str | None]:
    """Return (argv, stdin_text) for one agent call.

    `step` is a config entry: cli, model, permission, and optional overrides
    (bin, base, prompt, model_flag).
    """
    cli = step.get("cli", "none")
    spec = resolve(cli)
    if spec is None and not step.get("base"):
        raise ValueError(f"unknown cli {cli!r}: add `base` and `prompt` to the step config")

    binary = step.get("bin") or cli
    base = tuple(step.get("base") or (spec.base if spec else ()))
    mode = step.get("prompt") or (spec.prompt if spec else "stdin")
    permission = step.get("permission") or "acceptEdits"

    argv: list[str] = [binary]
    has_prompt_slot = any("{prompt}" in tok for tok in base)
    for tok in base:
        argv.append(tok.replace("{permission}", permission).replace("{prompt}", prompt))

    stdin_text: str | None = None
    if has_prompt_slot:
        mode = "argv"
    elif mode == "argv":
        argv.append(prompt)
    else:
        stdin_text = prompt

    mflag = step.get("model_flag")
    if model:
        if mflag:
            argv += [mflag, model]
        elif spec and spec.model:
            argv += [tok.replace("{model}", model) for tok in spec.model]
        elif not spec:
            argv += ["--model", model]
    return argv, stdin_text
