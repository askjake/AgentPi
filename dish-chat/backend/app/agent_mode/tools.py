import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
import asyncio
import shlex
import json
import re
from datetime import datetime

from langchain.tools import tool
from app.agent_mode.thought_interceptor import interceptor

# Root directory where agent-mode workspaces live
BASE_AGENT_WORKDIR = os.environ.get("AGENT_MODE_WORKDIR", "/tmp/home_agent")
Path(BASE_AGENT_WORKDIR).mkdir(parents=True, exist_ok=True)

# ============================================================================
# COMPREHENSIVE WHITELIST FOR HOME NETWORK & PROJECT MANAGEMENT
# ============================================================================

ALLOWED_BINARIES = {
    # Core system utilities
    "bash", "sh", "zsh", "ls", "cat", "grep", "find", "awk", "sed", "sort", 
    "uniq", "wc", "cut", "tr", "nl", "head", "tail", "less", "more",
    
    # Network connectivity & diagnostics
    "ping", "ping6", "traceroute", "traceroute6", "tracepath", "mtr", 
    "dig", "nslookup", "host", "whois",
    "nc", "netcat", "ncat", "socat", "curl", "wget", "telnet",
    
    # Network scanning & information
    "nmap", "masscan", "arp-scan", "arp", "arping",
    "ip", "ifconfig", "netstat", "ss", "route", "ip6tables", "iptables",
    "ethtool", "iwconfig", "iw", "iwlist", "wavemon",
    "tcpdump", "tshark", "wireshark",
    
    # Remote access & file transfer
    "ssh", "scp", "sftp", "rsync", "rclone",
    
    # System monitoring & performance
    "top", "htop", "atop", "ps", "pstree", "free", "uptime", 
    "df", "du", "iostat", "vmstat", "mpstat", "sar", 
    "w", "who", "last", "lastlog",
    
    # Hardware information
    "lshw", "lscpu", "lsusb", "lspci", "lsblk", "blkid", 
    "dmidecode", "sensors", "smartctl", "hdparm",
    "nvidia-smi", "radeontop",
    
    # System management
    "systemctl", "service", "journalctl", "dmesg",
    "uname", "hostname", "hostnamectl", "date", "timedatectl",
    "crontab", "at",
    
    # Development tools
    "git", "docker", "docker-compose", "kubectl", "helm",
    "python", "python3", "pip", "pip3", "node", "npm", "npx",
    "make", "cmake", "gcc", "g++", "cargo", "rustc",
    
    # Package management
    "apt", "apt-get", "dpkg", "yum", "dnf", "pacman", "brew",
    "snap", "flatpak",
    
    # Cloud/Infrastructure tools
    "aws", "az", "gcloud", "terraform", "ansible", "vagrant",
    
    # Database clients
    "psql", "mysql", "redis-cli", "mongo", "sqlite3",
    
    # Web servers & proxies
    "nginx", "apache2", "httpd", "caddy",
    
    # File operations
    "cp", "mv", "mkdir", "touch", "rm", "ln", "chmod", "chown",
    "tar", "gzip", "gunzip", "bzip2", "xz", "zip", "unzip",
    
    # Text editors (for config viewing)
    "nano", "vim", "vi", "emacs",
    
    # Security tools
    "openssl", "gpg", "ssh-keygen", "fail2ban-client",
    "ufw", "firewall-cmd",
}

# Dangerous command patterns that are BLOCKED
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",           # rm -rf /
    r"rm\s+--no-preserve-root", # rm --no-preserve-root
    r"mkfs\.",                 # filesystem formatting
    r"dd\s+if=.*of=/dev/",    # dangerous dd operations
    r":\(\)\{.*:\|:&\};:",    # fork bomb
    r"chmod\s+-R\s+777",      # dangerous permissions
    r"chown\s+-R\s+.*:",      # recursive ownership change
]


def _safe_workspace(chat_id: str) -> Path:
    """Return a per-chat workspace directory, creating it if needed."""
    ws = Path(BASE_AGENT_WORKDIR) / chat_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _venv_python(ws: Path) -> Path:
    """Resolve the Python executable inside the workspace virtualenv."""
    if os.name == "nt":
        return ws / ".venv" / "Scripts" / "python.exe"
    return ws / ".venv" / "bin" / "python"


def _validate_ip_address(ip: str) -> bool:
    """Validate IPv4 address format."""
    pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    if not re.match(pattern, ip):
        return False
    parts = ip.split(".")
    return all(0 <= int(part) <= 255 for part in parts)


def _validate_cidr(cidr: str) -> bool:
    """Validate CIDR notation (e.g., 192.168.1.0/24)."""
    pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$"
    if not re.match(pattern, cidr):
        return False
    ip_part, mask = cidr.split("/")
    if not _validate_ip_address(ip_part):
        return False
    return 0 <= int(mask) <= 32


def _detect_dangerous_command(command: str) -> Optional[str]:
    """Detect dangerous command patterns."""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"Blocked dangerous pattern: {pattern}"
    return None


def _detect_injection_patterns(command: str) -> Optional[str]:
    """Detect command injection patterns for security."""
    if not isinstance(command, str):
        return "Invalid command type"
    
    binary = shlex.split(command)[0] if command else ""
    
    # Allow pipes and redirects for bash, ssh (needed for remote commands)
    if binary in ["bash", "ssh", "scp", "sh", "zsh"]:
        return None
    
    # Check for shell metacharacters
    dangerous = [";", "&&", "||", "|", ">", ">>", "<", "`", "$(", "${", "\n"]
    for pattern in dangerous:
        if pattern in command:
            return f"Contains potentially dangerous pattern: {pattern}"
    
    return None


def _validate_command(command: str) -> tuple[bool, str]:
    """Validate command against whitelist and security policies.
    
    Returns (is_valid, error_message)
    """
    if not command or not isinstance(command, str):
        return False, "Invalid command format"
    
    # Check for dangerous patterns first
    danger_check = _detect_dangerous_command(command)
    if danger_check:
        return False, danger_check
    
    # Parse the binary
    try:
        parts = shlex.split(command)
        if not parts:
            return False, "Empty command"
        binary = parts[0]
    except ValueError as e:
        return False, f"Command parsing error: {e}"
    
    # Check if binary is whitelisted
    if binary not in ALLOWED_BINARIES:
        return False, f"Binary '{binary}' not in allowed list"
    
    # Check for injection patterns
    injection_check = _detect_injection_patterns(command)
    if injection_check:
        return False, injection_check
    
    return True, "OK"


# ============================================================================
# CORE AGENT TOOLS (Original + Enhanced)
# ============================================================================

@tool("agent_git_clone")
def agent_git_clone(chat_id: str, repo_url: str, branch: str = "main") -> str:
    """Clone (or update) a Git repository into the agent workspace.
    
    Parameters:
      - chat_id: Workspace identifier
      - repo_url: Git repository URL (https or ssh)
      - branch: Branch to checkout (default: main)
    
    Returns status of clone/pull operation.
    """
    ws = _safe_workspace(chat_id)
    repo_name = Path(repo_url).stem.replace(".git", "")
    repo_path = ws / repo_name
    
    try:
        if repo_path.exists():
            # Update existing repo
            result = subprocess.run(
                ["git", "-C", str(repo_path), "pull", "origin", branch],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return f"✅ Updated {repo_name} from {branch}\n{result.stdout}"
            return f"❌ Git pull failed:\n{result.stderr}"
        else:
            # Clone new repo
            result = subprocess.run(
                ["git", "clone", "-b", branch, repo_url, str(repo_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return f"✅ Cloned {repo_name} to {repo_path}\n{result.stdout}"
            return f"❌ Git clone failed:\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "❌ Git operation timed out"
    except Exception as e:
        return f"❌ Error: {e}"


@tool("agent_create_venv")
def agent_create_venv(chat_id: str, python_bin: Optional[str] = None) -> str:
    """Create (or recreate) a Python virtual environment inside the workspace.
    
    Parameters:
      - chat_id: Workspace identifier
      - python_bin: Python executable to use (default: python3)
    
    Returns status of venv creation.
    """
    ws = _safe_workspace(chat_id)
    venv_dir = ws / ".venv"
    
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    
    python = python_bin or "python3"
    try:
        result = subprocess.run(
            [python, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            pip_upgrade = subprocess.run(
                [str(_venv_python(ws)), "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return f"✅ Virtual environment created at {venv_dir}\n{pip_upgrade.stdout}"
        return f"❌ Venv creation failed:\n{result.stderr}"
    except Exception as e:
        return f"❌ Error creating venv: {e}"


@tool("agent_run_python")
def agent_run_python(
    chat_id: str,
    code: str,
    filename: str = "agent_script.py",
    use_venv: bool = True,
    workdir_subdir: Optional[str] = None,
) -> str:
    """Write Python code into the workspace and execute it.
    
    Parameters:
      - chat_id: Workspace identifier
      - code: Python code to execute
      - filename: Name for the script file
      - use_venv: Use virtualenv if available
      - workdir_subdir: Optional subdirectory to run in
    
    Returns stdout/stderr from execution.
    """
    ws = _safe_workspace(chat_id)
    
    if workdir_subdir:
        work_path = ws / workdir_subdir
        work_path.mkdir(parents=True, exist_ok=True)
    else:
        work_path = ws
    
    script_path = work_path / filename
    script_path.write_text(code)
    
    # Determine Python executable
    venv_py = _venv_python(ws)
    if use_venv and venv_py.exists():
        python_exec = str(venv_py)
    else:
        python_exec = "python3"
    
    try:
        result = subprocess.run(
            [python_exec, str(script_path)],
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = f"✅ Executed {script_path.name} (return code={result.returncode})\n"
        output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}"
        return output
    except subprocess.TimeoutExpired:
        return "❌ Script execution timed out (300s limit)"
    except Exception as e:
        return f"❌ Execution error: {e}"


@tool("agent_list_artifacts")
def agent_list_artifacts(chat_id: str) -> str:
    """List all files and artifacts in the workspace.
    
    Parameters:
      - chat_id: Workspace identifier
    
    Returns a formatted directory listing.
    """
    ws = _safe_workspace(chat_id)
    
    if not ws.exists() or not any(ws.iterdir()):
        return "No artifacts found in workspace."
    
    output = f"📁 Workspace: {ws}\n\n"
    
    for item in sorted(ws.rglob("*")):
        if item.is_file():
            rel_path = item.relative_to(ws)
            size = item.stat().st_size
            output += f"  {rel_path} ({size:,} bytes)\n"
    
    return output


@tool("agent_run_shell")
def agent_run_shell(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 600,
) -> str:
    """Execute whitelisted shell commands with security validation.
    
    This tool allows execution of pre-approved commands for system
    administration, network diagnostics, and development tasks.
    
    Parameters:
      - command: Shell command to execute
      - cwd: Working directory (optional)
      - timeout_seconds: Execution timeout (default: 600)
    
    Returns command output (stdout/stderr).
    
    Security: All commands are validated against whitelist and
    checked for dangerous patterns before execution.
    """
    # Validate command
    is_valid, error_msg = _validate_command(command)
    if not is_valid:
        return f"❌ Command rejected: {error_msg}\nCommand: {command}"
    
    # Execute command
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        
        output = f"Exit code: {result.returncode}\n"
        output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}"
        
        return output
    
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {timeout_seconds} seconds"
    except Exception as e:
        return f"❌ Execution error: {e}"


# ============================================================================
# HOME NETWORK MANAGEMENT TOOLS
# ============================================================================

@tool("agent_network_scan")
def agent_network_scan(
    chat_id: str,
    network: str = "192.168.1.0/24",
    scan_type: str = "ping",
    additional_opts: str = "",
) -> str:
    """Scan the home network for active devices.
    
    Discovers devices on your network using various scanning methods.
    Results can be saved to the persistent inventory.
    
    Parameters:
      - chat_id: Workspace identifier
      - network: Network to scan in CIDR notation (e.g., 192.168.1.0/24)
      - scan_type: Scan method - "ping" (fast), "nmap" (detailed), "arp" (local)
      - additional_opts: Additional options for the scan tool
    
    Returns list of discovered devices with details.
    """
    ws = _safe_workspace(chat_id)
    
    # Validate network CIDR
    if not _validate_cidr(network):
        return f"❌ Invalid CIDR notation: {network}. Use format: 192.168.1.0/24"
    
    output = f"🔍 Scanning network: {network} (method: {scan_type})\n\n"
    
    try:
        if scan_type == "ping":
            # Fast ping sweep
            base_ip = network.split("/")[0].rsplit(".", 1)[0]
            active_hosts = []
            
            for i in range(1, 255):
                ip = f"{base_ip}.{i}"
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    active_hosts.append(ip)
            
            if active_hosts:
                output += f"✅ Found {len(active_hosts)} active hosts:\n"
                for ip in active_hosts:
                    output += f"  • {ip}\n"
            else:
                output += "No active hosts found.\n"
        
        elif scan_type == "nmap":
            # Detailed nmap scan
            cmd = f"nmap -sn {network} {additional_opts}"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output += result.stdout
        
        elif scan_type == "arp":
            # ARP scan (local network only)
            cmd = f"arp-scan {network} {additional_opts}"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output += result.stdout
        
        else:
            return f"❌ Unknown scan_type: {scan_type}. Use: ping, nmap, or arp"
        
        # Save scan results to file
        scan_file = ws / f"network_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        scan_file.write_text(output)
        output += f"\n📄 Results saved to: {scan_file.name}"
        
        return output
    
    except subprocess.TimeoutExpired:
        return "❌ Network scan timed out"
    except Exception as e:
        return f"❌ Scan error: {e}"


@tool("agent_check_device")
def agent_check_device(
    ip_address: str,
    check_type: str = "ping",
    port: Optional[int] = None,
    ssh_user: Optional[str] = None,
) -> str:
    """Check status and connectivity of a specific network device.
    
    Performs various checks on a device: ping, port check, SSH availability.
    
    Parameters:
      - ip_address: IP address of the device
      - check_type: Type of check - "ping", "port", "ssh", "all"
      - port: Port number for port check (e.g., 22 for SSH, 80 for HTTP)
      - ssh_user: Username for SSH check (optional)
    
    Returns device status information.
    """
    if not _validate_ip_address(ip_address):
        return f"❌ Invalid IP address: {ip_address}"
    
    output = f"🔍 Checking device: {ip_address}\n\n"
    
    try:
        # Ping check
        if check_type in ["ping", "all"]:
            ping_result = subprocess.run(
                ["ping", "-c", "3", "-W", "2", ip_address],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if ping_result.returncode == 0:
                # Extract latency
                lines = ping_result.stdout.split("\n")
                for line in lines:
                    if "avg" in line or "time=" in line:
                        output += f"✅ Ping: ONLINE\n{line}\n\n"
                        break
            else:
                output += "❌ Ping: OFFLINE\n\n"
        
        # Port check
        if check_type in ["port", "all"] and port:
            nc_result = subprocess.run(
                ["nc", "-zv", "-w", "2", ip_address, str(port)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if nc_result.returncode == 0:
                output += f"✅ Port {port}: OPEN\n\n"
            else:
                output += f"❌ Port {port}: CLOSED or FILTERED\n\n"
        
        # SSH check
        if check_type in ["ssh", "all"]:
            if not ssh_user:
                ssh_user = "root"
            
            ssh_result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 f"{ssh_user}@{ip_address}", "echo SSH_OK"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "SSH_OK" in ssh_result.stdout:
                output += f"✅ SSH: Accessible (user: {ssh_user})\n\n"
            else:
                output += f"⚠️  SSH: Not accessible or key auth required\n\n"
        
        # System info if SSH accessible
        if check_type == "all" and ssh_user:
            info_result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", 
                 f"{ssh_user}@{ip_address}", 
                 "uname -a; uptime"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if info_result.returncode == 0:
                output += f"📊 System Info:\n{info_result.stdout}\n"
        
        return output
    
    except subprocess.TimeoutExpired:
        return f"❌ Device check timed out for {ip_address}"
    except Exception as e:
        return f"❌ Check error: {e}"


@tool("agent_save_device_info")
def agent_save_device_info(
    chat_id: str,
    device_name: str,
    ip_address: str,
    device_type: str = "unknown",
    notes: str = "",
    ssh_user: Optional[str] = None,
) -> str:
    """Save device information to the persistent inventory.
    
    Maintains a JSON database of all known network devices with their
    properties. This inventory persists across chat sessions.
    
    Parameters:
      - chat_id: Workspace identifier
      - device_name: Friendly name for the device
      - ip_address: Device IP address
      - device_type: Type of device (router, server, pi, nas, iot, etc.)
      - notes: Additional notes or description
      - ssh_user: SSH username if applicable
    
    Returns confirmation message.
    """
    ws = _safe_workspace(chat_id)
    inventory_file = ws / "device_inventory.json"
    
    if not _validate_ip_address(ip_address):
        return f"❌ Invalid IP address: {ip_address}"
    
    # Load existing inventory
    if inventory_file.exists():
        try:
            inventory = json.loads(inventory_file.read_text())
        except json.JSONDecodeError:
            inventory = {"devices": [], "last_updated": ""}
    else:
        inventory = {"devices": [], "last_updated": ""}
    
    # Create device entry
    device_entry = {
        "name": device_name,
        "ip": ip_address,
        "type": device_type,
        "notes": notes,
        "ssh_user": ssh_user,
        "last_updated": datetime.now().isoformat(),
    }
    
    # Update or add device
    existing_idx = next(
        (i for i, d in enumerate(inventory["devices"]) if d["ip"] == ip_address),
        None
    )
    
    if existing_idx is not None:
        inventory["devices"][existing_idx] = device_entry
        action = "Updated"
    else:
        inventory["devices"].append(device_entry)
        action = "Added"
    
    inventory["last_updated"] = datetime.now().isoformat()
    
    # Save inventory
    inventory_file.write_text(json.dumps(inventory, indent=2))
    
    return f"✅ {action} device '{device_name}' ({ip_address})\nTotal devices in inventory: {len(inventory['devices'])}"


@tool("agent_list_devices")
def agent_list_devices(chat_id: str, device_type: Optional[str] = None) -> str:
    """List all devices in the persistent inventory.
    
    Retrieves and displays all devices that have been saved using
    agent_save_device_info. Optionally filter by device type.
    
    Parameters:
      - chat_id: Workspace identifier
      - device_type: Filter by device type (optional)
    
    Returns formatted list of devices.
    """
    ws = _safe_workspace(chat_id)
    inventory_file = ws / "device_inventory.json"
    
    if not inventory_file.exists():
        return "📱 No device inventory found. Use agent_save_device_info() to add devices."
    
    try:
        inventory = json.loads(inventory_file.read_text())
        devices = inventory.get("devices", [])
    except json.JSONDecodeError:
        return "❌ Error reading inventory file (corrupted JSON)."
    
    if not devices:
        return "📱 Inventory file exists but contains no devices."
    
    # Filter by type if specified
    if device_type:
        devices = [d for d in devices if d.get("type") == device_type]
        if not devices:
            return f"No devices found with type: {device_type}"
    
    output = f"📱 Network Device Inventory ({len(devices)} devices)\n"
    output += f"Last updated: {inventory.get('last_updated', 'unknown')}\n\n"
    
    # Group by device type
    by_type: Dict[str, List] = {}
    for d in devices:
        dtype = d.get("type", "unknown")
        if dtype not in by_type:
            by_type[dtype] = []
        by_type[dtype].append(d)
    
    for dtype, device_list in sorted(by_type.items()):
        output += f"▶ {dtype.upper()}:\n"
        for d in sorted(device_list, key=lambda x: x["ip"]):
            output += f"  • {d['name']} - {d['ip']}"
            if d.get("ssh_user"):
                output += f" (SSH: {d['ssh_user']}@{d['ip']})"
            output += "\n"
            if d.get("notes"):
                output += f"    {d['notes']}\n"
        output += "\n"
    
    return output


@tool("agent_docker_ps")
def agent_docker_ps(
    host: Optional[str] = None,
    ssh_user: Optional[str] = None,
    show_all: bool = False,
) -> str:
    """List Docker containers on local or remote host.
    
    Parameters:
      - host: Remote host IP (optional, uses local docker if not specified)
      - ssh_user: SSH username for remote host
      - show_all: Show all containers including stopped (default: False)
    
    Returns list of running containers.
    """
    try:
        if host:
            # Remote docker via SSH
            if not ssh_user:
                return "❌ ssh_user required for remote host"
            
            # Build command with proper quoting
            docker_cmd = "docker ps"
            if show_all:
                docker_cmd += " -a"
            
            cmd = f'ssh {ssh_user}@{host} "{docker_cmd}"'
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            # Local docker
            cmd_list = ["docker", "ps"]
            if show_all:
                cmd_list.append("-a")
            
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=30,
            )
        
        if result.returncode == 0:
            return f"✅ Docker containers:\n{result.stdout}"
        else:
            return f"❌ Docker command failed:\n{result.stderr}"
    
    except Exception as e:
        return f"❌ Error: {e}"


@tool("agent_system_info")
def agent_system_info(
    host: Optional[str] = None,
    ssh_user: Optional[str] = None,
) -> str:
    """Gather comprehensive system information from local or remote host.
    
    Collects: OS info, CPU, memory, disk, uptime, network interfaces.
    
    Parameters:
      - host: Remote host IP (optional, uses localhost if not specified)
      - ssh_user: SSH username for remote host
    
    Returns detailed system information.
    """
    try:
        commands = [
            ("OS", "uname -a"),
            ("CPU", "lscpu | grep -E 'Model name|Socket|Core|Thread'"),
            ("Memory", "free -h"),
            ("Disk", "df -h | grep -v tmpfs"),
            ("Uptime", "uptime"),
            ("Load Average", "cat /proc/loadavg"),
            ("Network Interfaces", "ip -br addr"),
        ]
        
        output = "📊 System Information\n\n"
        
        for label, cmd in commands:
            if host:
                full_cmd = f"ssh -o ConnectTimeout=5 {ssh_user}@{host} '{cmd}'"
            else:
                full_cmd = cmd
            
            result = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                output += f"▶ {label}:\n{result.stdout}\n"
            else:
                output += f"▶ {label}: [Error retrieving]\n\n"
        
        return output
    
    except Exception as e:
        return f"❌ Error gathering system info: {e}"


# ============================================================================
# SMART HOME & IOT TOOLS
# ============================================================================

@tool("agent_mqtt_publish")
def agent_mqtt_publish(
    broker: str,
    topic: str,
    message: str,
    port: int = 1883,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """Publish a message to an MQTT broker.
    
    Useful for controlling smart home devices that use MQTT.
    
    Parameters:
      - broker: MQTT broker IP address or hostname
      - topic: MQTT topic to publish to
      - message: Message payload
      - port: MQTT port (default: 1883)
      - username: MQTT username (optional)
      - password: MQTT password (optional)
    
    Returns confirmation of message publication.
    """
    try:
        cmd = f'mosquitto_pub -h {broker} -p {port} -t "{topic}" -m "{message}"'
        
        if username:
            cmd += f" -u {username}"
        if password:
            cmd += f" -P {password}"
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode == 0:
            return f"✅ Published to {broker}/{topic}: {message}"
        else:
            return f"❌ MQTT publish failed:\n{result.stderr}"
    
    except Exception as e:
        return f"❌ Error: {e}"


@tool("agent_wake_on_lan")
def agent_wake_on_lan(mac_address: str, ip_address: str = "255.255.255.255") -> str:
    """Send a Wake-on-LAN magic packet to wake up a sleeping device.
    
    Parameters:
      - mac_address: Target device MAC address (format: AA:BB:CC:DD:EE:FF)
      - ip_address: Broadcast IP (default: 255.255.255.255)
    
    Returns confirmation of packet sent.
    """
    try:
        # Validate MAC address format
        mac_pattern = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
        if not re.match(mac_pattern, mac_address):
            return f"❌ Invalid MAC address format: {mac_address}"
        
        # Using etherwake or wakeonlan tool
        result = subprocess.run(
            ["wakeonlan", mac_address],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if result.returncode == 0:
            return f"✅ WOL magic packet sent to {mac_address}"
        else:
            return f"❌ WOL failed:\n{result.stderr}"
    
    except FileNotFoundError:
        return "❌ wakeonlan command not found. Install: apt install wakeonlan"
    except Exception as e:
        return f"❌ Error: {e}"
