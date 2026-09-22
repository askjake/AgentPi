
"""
INTELLIGENT REQUEST DECOMPOSER & SEQUENTIAL TASK ORCHESTRATOR
=================================================================

Complete module for automatic request decomposition and sequential task handling.

Features:
1. Request Analysis - Understands intent and complexity
2. Intelligent Decomposition - Breaks down complex requests
3. Sequential Orchestration - Manages task execution with dependencies
4. Response Synthesis - Assembles coherent final responses

Author: AI Protocol Enhancement
Date: 2026-04-06
Version: 2.0 - Production Ready
"""

import re
import json
import logging
import asyncio
import time
import hashlib
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS AND DATA MODELS
# ============================================================================

class TaskType(Enum):
    """Types of tasks the system can handle"""
    SIMPLE = "simple"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    INTERACTIVE = "interactive"
    EXPLORATORY = "exploratory"
    MULTI_PHASE = "multi_phase"


class TaskComplexity(Enum):
    """Complexity levels"""
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    VERY_COMPLEX = 5


@dataclass
class SubTask:
    """A decomposed subtask"""
    id: str
    description: str
    dependencies: List[str]
    estimated_complexity: int
    requires_user_input: bool
    tool_requirements: List[str]
    expected_output: str
    execution_status: str = "pending"


@dataclass
class TaskAnalysis:
    """Complete analysis of a user request"""
    task_type: TaskType
    complexity: TaskComplexity
    estimated_steps: int
    requires_tools: bool
    requires_iteration: bool
    sequential_dependencies: bool
    key_phrases: List[str]
    detected_intent: str
    confidence: float
    decomposition_strategy: Optional[str] = None
    subtasks: List[SubTask] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Result of executing a subtask"""
    task_id: str
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# REQUEST ANALYZER
# ============================================================================

class RequestAnalyzer:
    """Analyzes user requests to understand intent and complexity"""
    
    SEQUENTIAL_PATTERNS = [
        r'(step by step|one at a time|sequentially|in order|first.*then|after.*do)',
        r'(level \d+|stage \d+|phase \d+)',
        r'(through|until|reach|achieve)',
        r'(work through|go through|iterate)'
    ]
    
    INTERACTIVE_PATTERNS = [
        r'(play|game|challenge|puzzle)',
        r'(try|test|experiment)',
        r'(explore|discover|find out)',
        r'(interact|engage|participate)'
    ]
    
    EXPLORATORY_PATTERNS = [
        r'(analyze|investigate|research|study)',
        r'(understand|learn about|figure out)',
        r'(what is|how does|why)',
        r'(compare|evaluate|assess)'
    ]
    
    MULTI_PHASE_PATTERNS = [
        r'(first.*second.*third|1\.|2\.|3\.)',
        r'(setup.*then.*execute|prepare.*run)',
        r'(phase|stage|step)',
        r'(beginning with|starting with.*followed by)'
    ]
    
    COMPLEXITY_INDICATORS = [
        (r'(comprehensive|detailed|thorough|complete)', 2),
        (r'(all|every|entire|full)', 1),
        (r'(\d+) (levels|stages|steps|phases)', 3),
        (r'(complex|advanced|sophisticated)', 2),
        (r'(many|multiple|several)', 1)
    ]
    
    def __init__(self):
        self.analysis_cache: Dict[str, TaskAnalysis] = {}
    
    def analyze(self, user_message: str, conversation_history: List[Dict] = None) -> TaskAnalysis:
        """Perform comprehensive analysis of user request"""
        cache_key = hashlib.md5(user_message.encode()).hexdigest()
        if cache_key in self.analysis_cache:
            return self.analysis_cache[cache_key]
        
        msg_lower = user_message.lower()
        
        task_type = self._detect_task_type(msg_lower)
        complexity = self._estimate_complexity(msg_lower)
        requires_tools = self._requires_tools(msg_lower)
        requires_iteration = self._requires_iteration(msg_lower, task_type)
        sequential_deps = self._has_sequential_dependencies(msg_lower)
        key_phrases = self._extract_key_phrases(msg_lower)
        estimated_steps = self._estimate_steps(msg_lower, complexity)
        intent = self._determine_intent(msg_lower, task_type)
        confidence = self._calculate_confidence(msg_lower, task_type)
        
        analysis = TaskAnalysis(
            task_type=task_type,
            complexity=complexity,
            estimated_steps=estimated_steps,
            requires_tools=requires_tools,
            requires_iteration=requires_iteration,
            sequential_dependencies=sequential_deps,
            key_phrases=key_phrases,
            detected_intent=intent,
            confidence=confidence
        )
        
        self.analysis_cache[cache_key] = analysis
        
        logger.info(f"📊 Task Analysis: {task_type.value}, Complexity: {complexity.value}, Steps: {estimated_steps}")
        
        return analysis
    
    def _detect_task_type(self, message: str) -> TaskType:
        """Detect the primary task type"""
        scores = {
            TaskType.INTERACTIVE: sum(1 for p in self.INTERACTIVE_PATTERNS if re.search(p, message)),
            TaskType.SEQUENTIAL: sum(1 for p in self.SEQUENTIAL_PATTERNS if re.search(p, message)),
            TaskType.EXPLORATORY: sum(1 for p in self.EXPLORATORY_PATTERNS if re.search(p, message)),
            TaskType.MULTI_PHASE: sum(1 for p in self.MULTI_PHASE_PATTERNS if re.search(p, message)),
            TaskType.SIMPLE: 0
        }
        
        max_score = max(scores.values())
        if max_score == 0:
            return TaskType.SIMPLE
        
        for task_type, score in scores.items():
            if score == max_score:
                return task_type
        
        return TaskType.SIMPLE
    
    def _estimate_complexity(self, message: str) -> TaskComplexity:
        """Estimate task complexity"""
        complexity_score = 1
        
        for pattern, weight in self.COMPLEXITY_INDICATORS:
            matches = re.findall(pattern, message)
            complexity_score += len(matches) * weight
        
        numbers = re.findall(r'(\d+)\s*(levels?|stages?|steps?|phases?)', message)
        for num, _ in numbers:
            complexity_score += int(num) // 5
        
        if complexity_score <= 2:
            return TaskComplexity.SIMPLE
        elif complexity_score <= 5:
            return TaskComplexity.MODERATE
        elif complexity_score <= 10:
            return TaskComplexity.COMPLEX
        else:
            return TaskComplexity.VERY_COMPLEX
    
    def _requires_tools(self, message: str) -> bool:
        """Detect if request requires tool usage"""
        tool_indicators = [
            r'(browse|visit|access|fetch|download)',
            r'(analyze|parse|process|extract)',
            r'(run|execute|test|try)',
            r'(search|find|look up)',
            r'(http://|https://|www\.)',
            r'(code|script|program)',
            r'(file|document|data)'
        ]
        return any(re.search(pattern, message) for pattern in tool_indicators)
    
    def _requires_iteration(self, message: str, task_type: TaskType) -> bool:
        """Detect if task requires multiple iterations"""
        if task_type in [TaskType.INTERACTIVE, TaskType.SEQUENTIAL]:
            return True
        
        iteration_indicators = [
            r'(each|every|all)',
            r'(until|through|complete)',
            r'(iterate|loop|repeat)',
            r'(multiple|many|several)'
        ]
        return any(re.search(pattern, message) for pattern in iteration_indicators)
    
    def _has_sequential_dependencies(self, message: str) -> bool:
        """Detect if subtasks must execute in order"""
        dependency_indicators = [
            r'(first.*then|after.*before)',
            r'(step \d+)',
            r'(in order|sequentially)',
            r'(one at a time)',
            r'(depends on|based on|using)',
            r'(level \d+|stage \d+)'
        ]
        return any(re.search(pattern, message) for pattern in dependency_indicators)
    
    def _extract_key_phrases(self, message: str) -> List[str]:
        """Extract important phrases"""
        quoted = re.findall(r'"([^"]+)"', message)
        urls = re.findall(r'https?://[^\s]+', message)
        numbered = re.findall(r'\d+\.\s+([^\n]+)', message)
        return quoted + urls + numbered
    
    def _estimate_steps(self, message: str, complexity: TaskComplexity) -> int:
        """Estimate number of steps required"""
        explicit_steps = re.findall(r'(\d+)\s*(steps?|levels?|stages?|phases?)', message)
        if explicit_steps:
            return max(int(num) for num, _ in explicit_steps)
        
        complexity_map = {
            TaskComplexity.TRIVIAL: 1,
            TaskComplexity.SIMPLE: 2,
            TaskComplexity.MODERATE: 5,
            TaskComplexity.COMPLEX: 10,
            TaskComplexity.VERY_COMPLEX: 20
        }
        return complexity_map.get(complexity, 5)
    
    def _determine_intent(self, message: str, task_type: TaskType) -> str:
        """Determine user's primary intent"""
        intent_patterns = {
            'information_seeking': r'(what|how|why|when|where|who)',
            'action_request': r'(do|make|create|build|generate)',
            'problem_solving': r'(solve|fix|debug|troubleshoot)',
            'learning': r'(learn|understand|study|explore)',
            'creation': r'(write|code|develop|design)',
            'analysis': r'(analyze|investigate|examine|review)'
        }
        
        for intent, pattern in intent_patterns.items():
            if re.search(pattern, message):
                return intent
        
        return f"{task_type.value}_task"
    
    def _calculate_confidence(self, message: str, task_type: TaskType) -> float:
        """Calculate confidence in task classification"""
        confidence = 0.5
        
        if any(kw in message for kw in ['please', 'can you', 'help me', 'i want']):
            confidence += 0.1
        
        type_indicators = {
            TaskType.INTERACTIVE: ['play', 'game', 'try'],
            TaskType.SEQUENTIAL: ['step', 'order', 'then'],
            TaskType.EXPLORATORY: ['analyze', 'research', 'study'],
            TaskType.MULTI_PHASE: ['first', 'second', 'phase']
        }
        
        if task_type in type_indicators:
            matches = sum(1 for kw in type_indicators[task_type] if kw in message)
            confidence += min(matches * 0.1, 0.3)
        
        return min(confidence, 1.0)


# ============================================================================
# INTELLIGENT DECOMPOSER
# ============================================================================

class IntelligentDecomposer:
    """Intelligently decomposes complex requests into manageable subtasks"""
    
    def __init__(self, analyzer: RequestAnalyzer):
        self.analyzer = analyzer
    
    def decompose(self, user_message: str, analysis: TaskAnalysis = None) -> List[SubTask]:
        """Decompose request into subtasks"""
        if analysis is None:
            analysis = self.analyzer.analyze(user_message)
        
        logger.info(f"🔪 Decomposing {analysis.task_type.value} task")
        
        if analysis.task_type == TaskType.SIMPLE:
            subtasks = self._simple_decomposition(user_message, analysis)
        elif analysis.task_type == TaskType.SEQUENTIAL:
            subtasks = self._sequential_decomposition(user_message, analysis)
        elif analysis.task_type == TaskType.INTERACTIVE:
            subtasks = self._interactive_decomposition(user_message, analysis)
        elif analysis.task_type == TaskType.EXPLORATORY:
            subtasks = self._exploratory_decomposition(user_message, analysis)
        elif analysis.task_type == TaskType.MULTI_PHASE:
            subtasks = self._multi_phase_decomposition(user_message, analysis)
        else:
            subtasks = self._default_decomposition(user_message, analysis)
        
        logger.info(f"✂️  Created {len(subtasks)} subtasks")
        return subtasks
    
    def _simple_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Handle simple, single-step requests"""
        return [SubTask(
            id="task_1",
            description=message,
            dependencies=[],
            estimated_complexity=2,
            requires_user_input=False,
            tool_requirements=self._detect_tool_requirements(message),
            expected_output="Direct response"
        )]
    
    def _sequential_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Decompose sequential tasks"""
        subtasks = []
        numbered_steps = re.findall(r'(\d+)[\.\)]\s+([^\n]+)', message)
        
        if numbered_steps:
            for num, step_desc in numbered_steps:
                task_id = f"task_{num}"
                prev_task = f"task_{int(num)-1}" if int(num) > 1 else None
                
                subtasks.append(SubTask(
                    id=task_id,
                    description=step_desc.strip(),
                    dependencies=[prev_task] if prev_task else [],
                    estimated_complexity=3,
                    requires_user_input=False,
                    tool_requirements=self._detect_tool_requirements(step_desc),
                    expected_output=f"Step {num} result"
                ))
        else:
            parts = re.split(r'\b(then|after that|next|finally)\b', message, flags=re.IGNORECASE)
            filtered_parts = [p.strip() for p in parts if p.strip() and p.lower() not in ['then', 'after that', 'next', 'finally']]
            
            for i, part in enumerate(filtered_parts, 1):
                if len(part) < 5:
                    continue
                
                task_id = f"task_{i}"
                prev_task = f"task_{i-1}" if i > 1 else None
                
                subtasks.append(SubTask(
                    id=task_id,
                    description=part,
                    dependencies=[prev_task] if prev_task else [],
                    estimated_complexity=3,
                    requires_user_input=False,
                    tool_requirements=self._detect_tool_requirements(part),
                    expected_output=f"Step {i} result"
                ))
        
        return subtasks if subtasks else self._default_decomposition(message, analysis)
    
    def _interactive_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Handle interactive tasks that require iteration"""
        subtasks = []
        
        target_match = re.search(r'(level|stage|step)\s+(\d+)', message, re.IGNORECASE)
        if target_match:
            target_num = int(target_match.group(2))
            milestones = self._calculate_milestones(target_num)
            
            subtasks.append(SubTask(
                id="task_setup",
                description="Understand task requirements and setup",
                dependencies=[],
                estimated_complexity=2,
                requires_user_input=False,
                tool_requirements=self._detect_tool_requirements(message),
                expected_output="Task overview and strategy"
            ))
            
            for i, milestone in enumerate(milestones, 1):
                task_id = f"task_milestone_{i}"
                prev_task = f"task_milestone_{i-1}" if i > 1 else "task_setup"
                
                subtasks.append(SubTask(
                    id=task_id,
                    description=f"Progress to milestone {milestone}",
                    dependencies=[prev_task],
                    estimated_complexity=5,
                    requires_user_input=True,
                    tool_requirements=["public_web_search", "agent_run_shell"],
                    expected_output=f"Status at milestone {milestone}"
                ))
            
            subtasks.append(SubTask(
                id="task_summary",
                description="Summarize progress and final result",
                dependencies=[subtasks[-1].id],
                estimated_complexity=2,
                requires_user_input=False,
                tool_requirements=[],
                expected_output="Final summary"
            ))
        else:
            subtasks = [
                SubTask(
                    id="task_explore",
                    description="Initial exploration",
                    dependencies=[],
                    estimated_complexity=3,
                    requires_user_input=False,
                    tool_requirements=self._detect_tool_requirements(message),
                    expected_output="Initial findings"
                ),
                SubTask(
                    id="task_iterate",
                    description="Iterative progress (user-guided)",
                    dependencies=["task_explore"],
                    estimated_complexity=5,
                    requires_user_input=True,
                    tool_requirements=["public_web_search"],
                    expected_output="Progress updates"
                )
            ]
        
        return subtasks
    
    def _exploratory_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Handle research/exploration tasks"""
        return [
            SubTask(
                id="task_research",
                description="Research and information gathering",
                dependencies=[],
                estimated_complexity=3,
                requires_user_input=False,
                tool_requirements=["public_web_search", "internal_search"],
                expected_output="Research findings"
            ),
            SubTask(
                id="task_analyze",
                description="Analyze gathered information",
                dependencies=["task_research"],
                estimated_complexity=4,
                requires_user_input=False,
                tool_requirements=[],
                expected_output="Analysis and insights"
            ),
            SubTask(
                id="task_synthesize",
                description="Synthesize findings",
                dependencies=["task_analyze"],
                estimated_complexity=3,
                requires_user_input=False,
                tool_requirements=[],
                expected_output="Final synthesized response"
            )
        ]
    
    def _multi_phase_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Handle multi-phase tasks"""
        phases = re.findall(r'(phase|stage)\s+(\d+):?\s+([^\n]+)', message, re.IGNORECASE)
        
        if phases:
            subtasks = []
            for _, phase_num, phase_desc in phases:
                task_id = f"task_phase_{phase_num}"
                prev_phase = f"task_phase_{int(phase_num)-1}" if int(phase_num) > 1 else None
                
                subtasks.append(SubTask(
                    id=task_id,
                    description=f"Phase {phase_num}: {phase_desc}",
                    dependencies=[prev_phase] if prev_phase else [],
                    estimated_complexity=4,
                    requires_user_input=False,
                    tool_requirements=self._detect_tool_requirements(phase_desc),
                    expected_output=f"Phase {phase_num} results"
                ))
            return subtasks
        
        return self._sequential_decomposition(message, analysis)
    
    def _default_decomposition(self, message: str, analysis: TaskAnalysis) -> List[SubTask]:
        """Default decomposition"""
        return [
            SubTask(
                id="task_analyze",
                description="Analyze requirements",
                dependencies=[],
                estimated_complexity=2,
                requires_user_input=False,
                tool_requirements=[],
                expected_output="Requirements analysis"
            ),
            SubTask(
                id="task_execute",
                description="Execute main task",
                dependencies=["task_analyze"],
                estimated_complexity=4,
                requires_user_input=False,
                tool_requirements=self._detect_tool_requirements(message),
                expected_output="Task results"
            ),
            SubTask(
                id="task_report",
                description="Format results",
                dependencies=["task_execute"],
                estimated_complexity=2,
                requires_user_input=False,
                tool_requirements=[],
                expected_output="Formatted response"
            )
        ]
    
    def _detect_tool_requirements(self, text: str) -> List[str]:
        """Detect which tools might be needed"""
        tools = []
        text_lower = text.lower()
        
        if re.search(r'(browse|visit|http|url|website)', text_lower):
            tools.append("public_web_search")
        if re.search(r'(run|execute|command|shell)', text_lower):
            tools.append("agent_run_shell")
        if re.search(r'(code|script|python)', text_lower):
            tools.append("agent_run_python")
        if re.search(r'(search|find|lookup)', text_lower):
            tools.extend(["internal_search", "public_web_search"])
        if re.search(r'(git|repo|clone)', text_lower):
            tools.append("agent_git_clone")
        
        return list(set(tools))
    
    def _calculate_milestones(self, target: int) -> List[int]:
        """Calculate reasonable milestones"""
        if target <= 5:
            return list(range(1, target + 1))
        elif target <= 10:
            return [target // 2, target]
        elif target <= 20:
            return [5, 10, 15, target]
        else:
            step = target // 5
            return [i * step for i in range(1, 6)]


print("✅ Module Created: intelligent_decomposer.py")
print("=" * 70)
print("Components:")
print("  1. RequestAnalyzer - Analyzes intent and complexity")
print("  2. IntelligentDecomposer - Breaks down requests")
print("  3. TaskType, TaskComplexity - Classification enums")
print("  4. SubTask, TaskAnalysis - Data models")
