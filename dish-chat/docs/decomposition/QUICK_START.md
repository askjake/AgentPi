# AUTO-DECOMPOSER QUICK START
## agentpi001@10.73.184.59

## Current Status
✅ DEPLOYED - Phase 1 (Monitoring Mode)
📍 Location: /home/agentpi001/dish-chat/backend/app/core/decomposition/

## Quick Test

```bash
cd /home/agentpi001/dish-chat/backend
python3 << EOF
from app.core.decomposition import RequestAnalyzer

analyzer = RequestAnalyzer()
analysis = analyzer.analyze("Play through 20 levels of this game")

print(f"Task Type: {analysis.task_type.value}")
print(f"Complexity: {analysis.complexity.value}")
print(f"Steps: {analysis.estimated_steps}")
EOF
```

## Module Structure

- **RequestAnalyzer** - Analyzes complexity and intent
- **IntelligentDecomposer** - Breaks down complex requests
- **SequentialOrchestrator** - Executes with dependencies
- **ResponseSynthesizer** - Assembles responses
- **AutoDecomposingAgent** - Main interface

## Example Usage

```python
from app.core.decomposition import AutoDecomposingAgent

# Initialize (monitoring mode)
agent = AutoDecomposingAgent(enable_auto_decompose=False)

# Analyze without execution
result = agent.analyze_without_execution(user_message)

print(f"Should decompose: {result['should_decompose']}")
print(f"Task type: {result['analysis']['task_type']}")
print(f"Subtasks: {result['subtask_count']}")
```

## Rollback

```bash
cd /home/agentpi001/dish-chat/backend
rm -rf app/core/decomposition
tar -xzf /home/agentpi001/backups/decomposer_deploy_20260406_165400/backend_pre_decomposer.tar.gz
```

## Support Files

- DEPLOYMENT_REPORT.md - Full deployment details
- /home/agentpi001/backups/ - Backup location

## Next Phase

Phase 2: Integration with agent.py for request monitoring
