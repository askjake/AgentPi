# app/tools/cluster_inspect.py
import logging
import subprocess
from typing import Dict, List

from langchain.tools import tool

from app.agent_mode.thought_interceptor import interceptor

logger = logging.getLogger(__name__)

# Curated, read-only commands – expanded for more functionality
ALLOWED_TASKS: Dict[str, List[str]] = {
    # Sentry commands
    "sentry_claims": ["kubectl", "get", "sentryclaims", "-A", "-o", "wide"],
    "sentry_pods": ["kubectl", "get", "pods", "-n", "sentry", "-o", "wide"],
    "sentry_all_pods": ["kubectl", "get", "pods", "-A", "-o", "wide"],
    "sentry_helm": ["helm", "list", "-A"],
    
    # General kubectl commands
    "get_namespaces": ["kubectl", "get", "namespaces"],
    "get_nodes": ["kubectl", "get", "nodes", "-o", "wide"],
    "get_deployments": ["kubectl", "get", "deployments", "-A", "-o", "wide"],
    "get_services": ["kubectl", "get", "services", "-A", "-o", "wide"],
    "get_ingress": ["kubectl", "get", "ingress", "-A", "-o", "wide"],
    "get_configmaps": ["kubectl", "get", "configmaps", "-A"],
    "get_secrets": ["kubectl", "get", "secrets", "-A"],
    "get_pvcs": ["kubectl", "get", "pvc", "-A", "-o", "wide"],
    
    # ArgoCD commands
    "argocd_apps": ["kubectl", "get", "applications", "-n", "argocd", "-o", "wide"],
    
    # Helm commands
    "helm_list_all": ["helm", "list", "-A"],
    
    # Context commands
    "get_contexts": ["kubectl", "config", "get-contexts"],
    "current_context": ["kubectl", "config", "current-context"],
}


def _run(cmd: List[str]) -> str:
    """Execute a command and return output."""
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        logger.error("cluster_inspect failed to run %r: %s", cmd, e, exc_info=True)
        return f"cluster_inspect: error running {cmd!r}: {e}"

    out = proc.stdout.strip()
    err = proc.stderr.strip()
    
    if proc.returncode != 0:
        return (
            f"cluster_inspect: command {cmd!r} exited {proc.returncode}\n"
            f"STDOUT:\n{out}\n\nSTDERR:\n{err}"
        )

    if err:
        return f"STDOUT:\n{out}\n\nSTDERR (non-fatal):\n{err}"

    return out or "(no output)"


def _run_kubectl_namespace(namespace: str, resource: str, extra_args: List[str] = None) -> str:
    """Run kubectl get for a specific namespace."""
    cmd = ["kubectl", "get", resource, "-n", namespace]
    if extra_args:
        cmd.extend(extra_args)
    else:
        cmd.extend(["-o", "wide"])
    return _run(cmd)


def _run_kubectl_describe(namespace: str, resource_type: str, resource_name: str) -> str:
    """Run kubectl describe for a specific resource."""
    cmd = ["kubectl", "describe", resource_type, resource_name, "-n", namespace]
    return _run(cmd)


def _run_kubectl_logs(namespace: str, pod_name: str, tail: int = 100, container: str = None) -> str:
    """Get logs from a pod."""
    cmd = ["kubectl", "logs", pod_name, "-n", namespace, f"--tail={tail}"]
    if container:
        cmd.extend(["-c", container])
    return _run(cmd)


@tool("cluster_inspect")
def cluster_inspect(task: str) -> str:
    """
    Run *read-only* cluster inspections via curated commands.

    Supported tasks:
    - "list sentry claims" - List Sentry claims
    - "list sentry pods" - List pods in sentry namespace
    - "list all pods" - List all pods in all namespaces
    - "list sentry helm releases" - List Helm releases
    - "list namespaces" - List all namespaces
    - "list nodes" - List cluster nodes
    - "list deployments" - List all deployments
    - "list services" - List all services
    - "list ingress" - List all ingress resources
    - "list argocd apps" - List ArgoCD applications
    - "get contexts" - List kubectl contexts
    - "current context" - Show current kubectl context
    - "pods in <namespace>" - List pods in specific namespace
    - "describe pod <pod-name> in <namespace>" - Describe a pod
    - "logs from <pod-name> in <namespace>" - Get pod logs (last 100 lines)
    - "logs from <pod-name> in <namespace> tail 500" - Get pod logs with custom tail

    Returns raw text output for the agent to interpret.
    """
    interceptor.tool_call("cluster_inspect", params={"task": task})
    interceptor.thought(f"Inspecting cluster: {task}", "tool")
    
    t = task.lower().strip()
    
    # Parse and route the task
    result = None
    
    # Predefined tasks
    if "sentry" in t and "claim" in t:
        result = _run(ALLOWED_TASKS["sentry_claims"])
    elif "sentry" in t and ("pod" in t or "deployment" in t):
        result = _run(ALLOWED_TASKS["sentry_pods"])
    elif "all" in t and "pod" in t:
        result = _run(ALLOWED_TASKS["sentry_all_pods"])
    elif "sentry" in t and "helm" in t:
        result = _run(ALLOWED_TASKS["sentry_helm"])
    elif "list namespaces" in t or "get namespaces" in t:
        result = _run(ALLOWED_TASKS["get_namespaces"])
    elif "list nodes" in t or "get nodes" in t:
        result = _run(ALLOWED_TASKS["get_nodes"])
    elif "list deployments" in t:
        result = _run(ALLOWED_TASKS["get_deployments"])
    elif "list services" in t:
        result = _run(ALLOWED_TASKS["get_services"])
    elif "list ingress" in t:
        result = _run(ALLOWED_TASKS["get_ingress"])
    elif "argocd" in t and "app" in t:
        result = _run(ALLOWED_TASKS["argocd_apps"])
    elif "helm" in t and "list" in t:
        result = _run(ALLOWED_TASKS["helm_list_all"])
    elif "get contexts" in t or "list contexts" in t:
        result = _run(ALLOWED_TASKS["get_contexts"])
    elif "current context" in t:
        result = _run(ALLOWED_TASKS["current_context"])
    
    # Dynamic namespace queries
    elif "pods in" in t:
        # Extract namespace: "pods in chatbot-agent"
        parts = t.split("pods in")
        if len(parts) == 2:
            namespace = parts[1].strip()
            result = _run_kubectl_namespace(namespace, "pods")
    
    elif "describe pod" in t and " in " in t:
        # Extract pod and namespace: "describe pod my-pod in my-namespace"
        parts = t.split("describe pod")[1].split(" in ")
        if len(parts) == 2:
            pod_name = parts[0].strip()
            namespace = parts[1].strip()
            result = _run_kubectl_describe(namespace, "pod", pod_name)
    
    elif "logs from" in t and " in " in t:
        # Extract pod and namespace: "logs from my-pod in my-namespace"
        # Optional: "logs from my-pod in my-namespace tail 500"
        parts = t.split("logs from")[1].split(" in ")
        if len(parts) == 2:
            pod_part = parts[0].strip()
            namespace_part = parts[1].strip()
            
            # Check for tail parameter
            tail = 100
            if "tail" in namespace_part:
                ns_parts = namespace_part.split("tail")
                namespace = ns_parts[0].strip()
                try:
                    tail = int(ns_parts[1].strip())
                except:
                    tail = 100
            else:
                namespace = namespace_part
            
            result = _run_kubectl_logs(namespace, pod_part, tail=tail)
    
    # If no match found
    if result is None:
        result = (
            "cluster_inspect: unsupported task. Try one of:\n"
            "- 'list sentry claims/pods/helm releases'\n"
            "- 'list namespaces/nodes/deployments/services/ingress'\n"
            "- 'list argocd apps'\n"
            "- 'get contexts' or 'current context'\n"
            "- 'pods in <namespace>'\n"
            "- 'describe pod <pod-name> in <namespace>'\n"
            "- 'logs from <pod-name> in <namespace> [tail N]'"
        )
        interceptor.tool_call("cluster_inspect", result="Unsupported task")
        return result
    
    # Log completion
    if "error" not in result.lower() and "failed" not in result.lower():
        interceptor.tool_call("cluster_inspect", result="Command completed successfully")
    else:
        interceptor.tool_call("cluster_inspect", result="Command failed or returned error")
    
    return result
