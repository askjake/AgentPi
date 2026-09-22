
"""
MAIN INTEGRATION MODULE
========================

Brings together all components into a single, easy-to-use interface
for automatic request decomposition and sequential task handling.
"""

import asyncio
import sys
sys.path.insert(0, '/tmp/agent_workspace_decomposer_dev')

from .intelligent_decomposer import (
    RequestAnalyzer, IntelligentDecomposer, TaskType, 
    TaskComplexity, SubTask, TaskAnalysis
)
from .task_orchestrator import (
    SequentialOrchestrator, ResponseSynthesizer, 
    UserGuidance, ExecutionResult
)


# ============================================================================
# MAIN INTEGRATION CLASS
# ============================================================================

class AutoDecomposingAgent:
    """
    Main agent class that automatically decomposes complex requests
    and handles sequential task execution.
    
    Usage:
        agent = AutoDecomposingAgent(llm_executor=my_llm_function)
        result = await agent.process_request("Your complex request here")
    """
    
    def __init__(self, llm_executor=None, enable_auto_decompose: bool = True):
        """
        Initialize the agent.
        
        Args:
            llm_executor: Async function to execute LLM calls
            enable_auto_decompose: If True, automatically decompose complex requests
        """
        self.analyzer = RequestAnalyzer()
        self.decomposer = IntelligentDecomposer(self.analyzer)
        self.orchestrator = SequentialOrchestrator(llm_executor)
        self.synthesizer = ResponseSynthesizer()
        self.enable_auto_decompose = enable_auto_decompose
        
        # Configuration thresholds
        self.complexity_threshold = TaskComplexity.MODERATE
        self.auto_decompose_types = [
            TaskType.SEQUENTIAL,
            TaskType.EXPLORATORY,
            TaskType.MULTI_PHASE
        ]
    
    async def process_request(self, user_message: str, 
                            conversation_history: list = None,
                            user_callback=None) -> dict:
        """
        Process a user request with automatic decomposition if needed.
        
        Args:
            user_message: The user's request
            conversation_history: Previous conversation messages
            user_callback: Optional callback for user interaction
            
        Returns:
            Response dictionary with 'response', 'success', and metadata
        """
        # Step 1: Analyze the request
        analysis = self.analyzer.analyze(user_message, conversation_history)
        
        # Step 2: Decide if decomposition is needed
        should_decompose = self._should_decompose(analysis)
        
        if not should_decompose:
            # Simple request - return guidance to process normally
            return {
                'response': None,  # Signal to process normally
                'should_decompose': False,
                'analysis': analysis,
                'guidance': "Request is simple enough for direct processing"
            }
        
        # Step 3: Decompose the request
        subtasks = self.decomposer.decompose(user_message, analysis)
        
        # Step 4: Generate user guidance
        guidance = UserGuidance.generate_guidance(analysis, subtasks)
        
        # For interactive tasks, return guidance first
        if analysis.task_type == TaskType.INTERACTIVE:
            return {
                'response': guidance,
                'should_decompose': True,
                'requires_iteration': True,
                'analysis': analysis,
                'subtasks': subtasks,
                'next_action': 'await_user_confirmation'
            }
        
        # Step 5: Execute subtasks
        results = await self.orchestrator.execute(subtasks, user_callback)
        
        # Step 6: Synthesize final response
        final_response = self.synthesizer.synthesize(subtasks, results, user_message)
        
        # Add analysis metadata
        final_response['analysis'] = {
            'task_type': analysis.task_type.value,
            'complexity': analysis.complexity.value,
            'confidence': analysis.confidence,
            'decomposed': True
        }
        
        return final_response
    
    def _should_decompose(self, analysis: TaskAnalysis) -> bool:
        """Determine if request should be decomposed"""
        if not self.enable_auto_decompose:
            return False
        
        # Decompose if complexity exceeds threshold
        if analysis.complexity.value >= self.complexity_threshold.value:
            return True
        
        # Decompose if task type requires it
        if analysis.task_type in self.auto_decompose_types:
            return True
        
        # Decompose if sequential dependencies detected
        if analysis.sequential_dependencies:
            return True
        
        # Decompose if many steps estimated
        if analysis.estimated_steps >= 5:
            return True
        
        return False
    
    def analyze_without_execution(self, user_message: str) -> dict:
        """
        Analyze a request without executing it (useful for dry-run).
        
        Returns:
            Dictionary with analysis and decomposition plan
        """
        analysis = self.analyzer.analyze(user_message)
        
        should_decompose = self._should_decompose(analysis)
        
        if should_decompose:
            subtasks = self.decomposer.decompose(user_message, analysis)
            guidance = UserGuidance.generate_guidance(analysis, subtasks)
        else:
            subtasks = []
            guidance = "No decomposition needed"
        
        return {
            'analysis': {
                'task_type': analysis.task_type.value,
                'complexity': analysis.complexity.value,
                'estimated_steps': analysis.estimated_steps,
                'requires_tools': analysis.requires_tools,
                'requires_iteration': analysis.requires_iteration,
                'sequential_dependencies': analysis.sequential_dependencies,
                'confidence': analysis.confidence
            },
            'should_decompose': should_decompose,
            'subtask_count': len(subtasks),
            'subtasks': [
                {
                    'id': task.id,
                    'description': task.description,
                    'dependencies': task.dependencies,
                    'complexity': task.estimated_complexity,
                    'requires_user_input': task.requires_user_input,
                    'tools': task.tool_requirements
                }
                for task in subtasks
            ],
            'guidance': guidance
        }


print("✅ Module Created: auto_decomposer.py")
print("=" * 70)
print("Main Interface: AutoDecomposingAgent")
print("\nUsage:")
print("  agent = AutoDecomposingAgent(llm_executor=my_function)")
print("  result = await agent.process_request('complex request')")
print("\nFeatures:")
print("  ✓ Automatic complexity analysis")
print("  ✓ Intelligent decomposition")
print("  ✓ Sequential task orchestration")
print("  ✓ Dependency management")
print("  ✓ Response synthesis")
