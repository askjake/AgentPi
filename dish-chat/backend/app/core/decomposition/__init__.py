"""
Auto-Decomposer Module
======================

Automatic request decomposition and sequential task handling.

Status: Phase 1 - Monitoring Only
Date: 2026-04-06
Server: agentpi001@10.73.184.59
"""

from .auto_decomposer import AutoDecomposingAgent
from .intelligent_decomposer import (
    RequestAnalyzer,
    IntelligentDecomposer,
    TaskType,
    TaskComplexity,
    SubTask,
    TaskAnalysis
)
from .task_orchestrator import (
    SequentialOrchestrator,
    ResponseSynthesizer,
    UserGuidance,
    ExecutionResult
)

__all__ = [
    'AutoDecomposingAgent',
    'RequestAnalyzer',
    'IntelligentDecomposer',
    'SequentialOrchestrator',
    'ResponseSynthesizer',
    'UserGuidance',
    'TaskType',
    'TaskComplexity',
    'SubTask',
    'TaskAnalysis',
    'ExecutionResult'
]

__version__ = '1.0.0'
__status__ = 'monitoring'
__server__ = 'agentpi001'
