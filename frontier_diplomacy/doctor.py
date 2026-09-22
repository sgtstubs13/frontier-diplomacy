"""Preflight checks for configuration and provider credentials."""

import os

from .registry import LabRegistry

PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
}


def check_registry(registry: LabRegistry, *, require_keys: bool = False) -> list[str]:
    issues = []
    for lab in registry.all(enabled_only=True):
        if lab.model.strip().upper() in {"MODEL_ID", "TODO", "TBD"}:
            issues.append(f"ERROR {lab.id}: model is still a placeholder ({lab.model})")
        if lab.provider not in PROVIDER_ENV:
            issues.append(f"ERROR {lab.id}: unsupported provider '{lab.provider}'")
            continue
        if require_keys and not any(os.environ.get(name) for name in PROVIDER_ENV[lab.provider]):
            issues.append(f"ERROR {lab.id}: missing API key ({' or '.join(PROVIDER_ENV[lab.provider])})")
    return issues
