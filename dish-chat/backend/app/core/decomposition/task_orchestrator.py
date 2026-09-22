
"""
SEQUENTIAL TASK ORCHESTRATOR & RESPONSE SYNTHESIZER
====================================================

Handles execution of decomposed tasks with proper dependency management
and synthesizes coherent final responses.
"""

import asyncio
import time
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

# Import from our decomposer module
import sys
sys.path.insert(0, '/tmp/agent_workspace_decomposer_dev')
from .intelligent_decomposer import SubTask, TaskAnalysis, ExecutionResult

logger = logging.getLogger(__name__)


# ============================================================================
# SEQUENTIAL ORCHESTRATOR
# ============================================================================

class SequentialOrchestrator:
    """
    Orchestrates execution of decomposed tasks, managing dependencies
    and handling sequential vs parallel execution appropriately.
    """
    
    def __init__(self, llm_executor: Callable = None):
        """
        Args:
            llm_executor: Function to execute LLM calls (async)
                         Signature: async def executor(prompt: str, tools: List[str]) -> Dict
        """
        self.llm_executor = llm_executor or self._default_executor
        self.execution_history: List[ExecutionResult] = []
        self.subtask_results: Dict[str, ExecutionResult] = {}
    
    async def execute(self, subtasks: List[SubTask], 
                     user_callback: Callable = None) -> List[ExecutionResult]:
        """
        Execute subtasks in the correct order, respecting dependencies.
        
        Args:
            subtasks: List of SubTask objects
            user_callback: Optional callback for user interaction
                          Signature: async def callback(subtask: SubTask) -> str
                          
        Returns:
            List of ExecutionResult objects
        """
        logger.info(f"🚀 Starting orchestration of {len(subtasks)} subtasks")
        
        results = []
        completed_tasks = set()
        
        task_map = {task.id: task for task in subtasks}
        
        for subtask in subtasks:
            # Wait for dependencies
            if subtask.dependencies:
                logger.info(f"⏳ Waiting for dependencies: {subtask.dependencies}")
                for dep_id in subtask.dependencies:
                    if dep_id not in completed_tasks:
                        if dep_id in self.subtask_results:
                            dep_result = self.subtask_results[dep_id]
                            if not dep_result.success:
                                result = ExecutionResult(
                                    task_id=subtask.id,
                                    success=False,
                                    output=None,
                                    error=f"Dependency {dep_id} failed"
                                )
                                results.append(result)
                                self.subtask_results[subtask.id] = result
                                continue
            
            # Execute subtask
            logger.info(f"▶️  Executing: {subtask.id} - {subtask.description[:50]}...")
            
            try:
                start_time = time.time()
                
                # Handle user input if required
                if subtask.requires_user_input and user_callback:
                    user_input = await user_callback(subtask)
                    context = f"User provided: {user_input}\n\n"
                else:
                    context = ""
                
                # Build context from previous results
                context += self._build_context_from_history(subtask)
                
                # Execute task
                output = await self._execute_subtask(subtask, context)
                
                execution_time = time.time() - start_time
                
                result = ExecutionResult(
                    task_id=subtask.id,
                    success=True,
                    output=output,
                    execution_time=execution_time,
                    metadata={'context_length': len(context)}
                )
                
                logger.info(f"✅ Completed {subtask.id} in {execution_time:.2f}s")
                
            except Exception as e:
                logger.error(f"❌ Failed {subtask.id}: {str(e)}")
                result = ExecutionResult(
                    task_id=subtask.id,
                    success=False,
                    output=None,
                    error=str(e),
                    execution_time=time.time() - start_time
                )
            
            results.append(result)
            self.subtask_results[subtask.id] = result
            completed_tasks.add(subtask.id)
            self.execution_history.append(result)
        
        success_count = sum(1 for r in results if r.success)
        logger.info(f"🏁 Orchestration complete: {success_count}/{len(subtasks)} succeeded")
        return results
    
    def _build_context_from_history(self, current_task: SubTask) -> str:
        """Build context from results of dependency tasks"""
        if not current_task.dependencies:
            return ""
        
        context = "## Context from previous steps:\n\n"
        
        for dep_id in current_task.dependencies:
            if dep_id in self.subtask_results:
                dep_result = self.subtask_results[dep_id]
                if dep_result.success:
                    context += f"### {dep_id}:\n"
                    context += f"{dep_result.output}\n\n"
        
        context += "## Current task:\n"
        context += f"{current_task.description}\n\n"
        
        return context
    
    async def _execute_subtask(self, subtask: SubTask, context: str) -> str:
        """Execute a single subtask"""
        prompt = f"{context}\n\nTask: {subtask.description}\n"
        
        if subtask.tool_requirements:
            prompt += f"\nAvailable tools: {', '.join(subtask.tool_requirements)}\n"
        
        result = await self.llm_executor(prompt, subtask.tool_requirements)
        
        return result.get('response', str(result))
    
    async def _default_executor(self, prompt: str, tools: List[str]) -> Dict[str, Any]:
        """Default executor for testing"""
        await asyncio.sleep(0.1)
        
        return {
            'response': f"[Simulated response to: {prompt[:100]}...]",
            'tools_used': tools
        }


# ============================================================================
# RESPONSE SYNTHESIZER
# ============================================================================

class ResponseSynthesizer:
    """
    Synthesizes final coherent response from multiple subtask results,
    handling both successful sequences and partial failures gracefully.
    """
    
    def synthesize(self, subtasks: List[SubTask], 
                   results: List[ExecutionResult],
                   original_request: str) -> Dict[str, Any]:
        """
        Synthesize final response from subtask results.
        
        Args:
            subtasks: Original subtasks
            results: Execution results
            original_request: User's original request
            
        Returns:
            Final response dictionary
        """
        logger.info(f"🔧 Synthesizing response from {len(results)} results")
        
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        if not successful:
            return self._handle_complete_failure(subtasks, results, original_request)
        
        if failed:
            return self._handle_partial_success(subtasks, successful, failed, original_request)
        
        return self._handle_complete_success(subtasks, successful, original_request)
    
    def _handle_complete_success(self, subtasks: List[SubTask], 
                                 results: List[ExecutionResult],
                                 original_request: str) -> Dict[str, Any]:
        """All subtasks succeeded"""
        response = f"# Response to: {original_request[:100]}...\n\n"
        
        has_dependencies = any(task.dependencies for task in subtasks)
        
        if has_dependencies:
            response += "I've completed this task in multiple steps:\n\n"
            for i, (task, result) in enumerate(zip(subtasks, results), 1):
                response += f"## Step {i}: {task.description}\n\n"
                response += f"{result.output}\n\n"
        else:
            response += "Here's what I found:\n\n"
            for result in results:
                response += f"{result.output}\n\n"
        
        total_time = sum(r.execution_time for r in results)
        response += f"\n---\n*Completed in {len(results)} steps ({total_time:.1f}s total)*"
        
        return {
            'response': response,
            'success': True,
            'subtask_count': len(subtasks),
            'execution_time': total_time,
            'metadata': {
                'decomposed': True,
                'all_successful': True,
                'steps': len(results)
            }
        }
    
    def _handle_partial_success(self, subtasks: List[SubTask],
                                successful: List[ExecutionResult],
                                failed: List[ExecutionResult],
                                original_request: str) -> Dict[str, Any]:
        """Some subtasks failed"""
        response = f"# Partial Response to: {original_request[:100]}...\n\n"
        response += f"⚠️  Completed {len(successful)}/{len(subtasks)} steps successfully.\n\n"
        
        response += "## Completed Steps:\n\n"
        for result in successful:
            task = next((t for t in subtasks if t.id == result.task_id), None)
            if task:
                response += f"### ✅ {task.description}\n\n"
                response += f"{result.output}\n\n"
        
        response += "## Steps That Encountered Issues:\n\n"
        for result in failed:
            task = next((t for t in subtasks if t.id == result.task_id), None)
            if task:
                response += f"### ❌ {task.description}\n\n"
                response += f"Error: {result.error}\n\n"
        
        response += "\n## Next Steps:\n\n"
        response += "To continue, you can:\n"
        response += "1. Address the errors mentioned above\n"
        response += "2. Provide additional information if needed\n"
        response += "3. Try a different approach for the failed steps\n"
        
        return {
            'response': response,
            'success': False,
            'partial': True,
            'successful_count': len(successful),
            'failed_count': len(failed),
            'metadata': {
                'decomposed': True,
                'partial_success': True
            }
        }
    
    def _handle_complete_failure(self, subtasks: List[SubTask],
                                 results: List[ExecutionResult],
                                 original_request: str) -> Dict[str, Any]:
        """All subtasks failed"""
        response = f"# Unable to Complete: {original_request[:100]}...\n\n"
        response += "❌ Unfortunately, all steps encountered errors.\n\n"
        
        response += "## Errors Encountered:\n\n"
        for result in results:
            task = next((t for t in subtasks if t.id == result.task_id), None)
            if task:
                response += f"### {task.description}\n"
                response += f"Error: {result.error}\n\n"
        
        response += "\n## Suggested Actions:\n\n"
        response += "This request may need:\n"
        response += "- Different phrasing or more specific details\n"
        response += "- Breaking down into smaller, simpler parts\n"
        response += "- Additional context or information\n"
        response += "- A different approach altogether\n"
        
        return {
            'response': response,
            'success': False,
            'partial': False,
            'metadata': {
                'decomposed': True,
                'complete_failure': True
            }
        }


# ============================================================================
# USER INTERACTION GUIDANCE
# ============================================================================

class UserGuidance:
    """
    Provides intelligent guidance to users for requests that require
    decomposition or iteration.
    """
    
    @staticmethod
    def generate_guidance(analysis: TaskAnalysis, subtasks: List[SubTask]) -> str:
        """Generate user guidance based on task analysis"""
        
        if analysis.task_type.value == "interactive":
            return UserGuidance._interactive_guidance(analysis, subtasks)
        elif analysis.task_type.value == "sequential":
            return UserGuidance._sequential_guidance(analysis, subtasks)
        elif analysis.complexity.value >= 4:  # Complex or very complex
            return UserGuidance._complexity_guidance(analysis, subtasks)
        else:
            return None
    
    @staticmethod
    def _interactive_guidance(analysis: TaskAnalysis, subtasks: List[SubTask]) -> str:
        """Guidance for interactive tasks"""
        guidance = "## 🎮 Interactive Task Detected\n\n"
        guidance += "This task requires iterative progress. Here's how we'll proceed:\n\n"
        
        for i, task in enumerate(subtasks, 1):
            status = "🔄 Next" if i == 1 else "⏸️  Pending"
            guidance += f"{status} **Step {i}**: {task.description}\n"
            if task.requires_user_input:
                guidance += f"   *(Will need your input at this stage)*\n"
        
        guidance += f"\n**Let's start with Step 1**: {subtasks[0].description}\n"
        return guidance
    
    @staticmethod
    def _sequential_guidance(analysis: TaskAnalysis, subtasks: List[SubTask]) -> str:
        """Guidance for sequential tasks"""
        guidance = "## 📋 Sequential Task Plan\n\n"
        guidance += f"I've broken this down into {len(subtasks)} steps:\n\n"
        
        for i, task in enumerate(subtasks, 1):
            guidance += f"{i}. {task.description}\n"
            if task.dependencies:
                deps = ', '.join(task.dependencies)
                guidance += f"   *(Depends on: {deps})*\n"
        
        guidance += "\n**Proceeding with execution...**\n"
        return guidance
    
    @staticmethod
    def _complexity_guidance(analysis: TaskAnalysis, subtasks: List[SubTask]) -> str:
        """Guidance for complex tasks"""
        guidance = "## 🔍 Complex Request Detected\n\n"
        guidance += f"This is a {analysis.complexity.value.name.lower()} task with approximately {analysis.estimated_steps} steps.\n\n"
        guidance += "I've decomposed it into manageable phases:\n\n"
        
        for i, task in enumerate(subtasks, 1):
            guidance += f"**Phase {i}**: {task.description}\n"
        
        guidance += "\n**Starting execution...**\n"
        return guidance


print("✅ Module Created: task_orchestrator.py")
print("=" * 70)
print("Components:")
print("  1. SequentialOrchestrator - Manages task execution")
print("  2. ResponseSynthesizer - Assembles final responses")
print("  3. UserGuidance - Provides user guidance")
