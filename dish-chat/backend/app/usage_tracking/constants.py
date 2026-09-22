MODEL_PRICING = {
    "Claude-3.5-Sonnet": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "Claude-3.7-Sonnet": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "Claude-Sonnet-4": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "us.anthropic.claude-sonnet-4-20250514-v1:0": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "anthropic.claude-3-5-haiku-20241022-v1:0": {
        "input": 0.0008 / 1000,
        "cache_read": 0.00008 / 1000,
        "cache_create": 0.001 / 1000,
        "output": 0.004 / 1000,
    },
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": {
        "input": 0.0008 / 1000,  # $0.80 per million input tokens (typical Haiku pricing)
        "output": 0.004 / 1000,   # $4.00 per million output tokens
        "cache_read": 0.00008 / 1000,  # 10% of input for cache reads
        "cache_create": 0.001 / 1000,  # 1.25x input for cache writes
    },
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": {
        "input": 0.0008 / 1000,
        "cache_read": 0.00008 / 1000,
        "cache_create": 0.001 / 1000,
        "output": 0.004 / 1000,
    },
    "us.anthropic.claude-sonnet-4-6": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },
    "global.anthropic.claude-sonnet-4-6": {
        "input": 0.003 / 1000,
        "cache_read": 0.0003 / 1000,
        "cache_create": 0.00375 / 1000,
        "output": 0.015 / 1000,
    },



}
