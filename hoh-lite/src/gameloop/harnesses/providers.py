"""Pinned provider configuration shared by role harness adapters."""

from __future__ import annotations

from typing import Any


def build_bailian_opencode_config(base_url: str) -> dict[str, Any]:
    if not base_url.strip():
        raise ValueError("BAILIAN_BASE_URL is required")
    return {
        "snapshot": False,
        "autoupdate": False,
        "plugin": [],
        "permission": {"task": "deny"},
        "agent": {
            "compaction": {
                "prompt": (
                    "You are compacting an agent session. Return only the requested "
                    "Markdown summary as plain text. Never call tools or emit tool-call "
                    "syntax, JSON tool requests, code execution requests, or commentary. "
                    "Do not continue the implementation; only summarize it."
                ),
                "temperature": 0,
                "steps": 1,
                "permission": {"*": "deny"},
            }
        },
        "compaction": {
            "auto": True,
            "prune": True,
            "tail_turns": 1,
            "preserve_recent_tokens": 4000,
            "reserved": 32768,
        },
        "watcher": {
            "ignore": ["assets/library/**", "assets/library-oga/**", ".godot/**"]
        },
        "provider": {
            "bailian": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Bailian",
                "options": {
                    "baseURL": base_url.rstrip("/"),
                    "apiKey": "{env:BAILIAN_API_KEY}",
                },
                "models": {
                    "deepseek-v4-pro": {
                        "name": "deepseek-v4-pro",
                        "limit": {"context": 131072, "output": 32768},
                    }
                },
            }
        },
    }


def build_pjlab_pi_models_config(base_url: str) -> dict[str, Any]:
    if not base_url.strip():
        raise ValueError("PJLAB_BASE_URL is required")
    return {
        "providers": {
            "pjlab": {
                "baseUrl": base_url.rstrip("/"),
                "api": "openai-completions",
                "apiKey": "$PJLAB_API_KEY",
                "authHeader": True,
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [
                    {
                        "id": "minimax-m3",
                        "name": "MiniMax M3 (PJLab)",
                        "reasoning": True,
                        "input": ["text", "image"],
                        "contextWindow": 954112,
                        "maxTokens": 32768,
                        "cost": {
                            "input": 0,
                            "output": 0,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                        },
                    }
                ],
            }
        }
    }


def build_pi_settings_config() -> dict[str, Any]:
    return {
        "defaultProvider": "pjlab",
        "defaultModel": "minimax-m3",
        "defaultThinkingLevel": "high",
        "defaultProjectTrust": "never",
        "enableInstallTelemetry": False,
        "retry": {
            "enabled": True,
            "maxRetries": 10,
            "baseDelayMs": 1000,
            "provider": {"maxRetries": 2, "maxRetryDelayMs": 60000},
        },
    }
