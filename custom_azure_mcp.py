#!/usr/bin/env python3
"""
Custom Azure MCP Server
Dual-transport architecture supporting both stdio and HTTP
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging - log to file to avoid interfering with MCP stdio communication
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('azure_mcp_server.log'),
        # Only add console handler for HTTP transport (not stdio)
        # Will be configured per transport in main()
    ]
)
logger = logging.getLogger('azure_mcp_server')

class AzureCredentials:
    """Manages Azure authentication and clients"""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, subscription_id: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.subscription_id = subscription_id
        
        # Initialize Azure credentials
        self.credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Initialize Azure clients
        self.compute_client = ComputeManagementClient(self.credential, subscription_id)
        self.network_client = NetworkManagementClient(self.credential, subscription_id)
        self.resource_client = ResourceManagementClient(self.credential, subscription_id)


# Global credentials instance (will be initialized in main)
azure_creds: Optional[AzureCredentials] = None

# Initialize FastMCP server (will be recreated in main for HTTP with proper host/port)
app = FastMCP(name="custom-azure-mcp")


@app.tool()
async def deploy_vm(
    resource_group: str,
    vm_name: str, 
    admin_password: str,
    location: str = "eastus",
    vm_size: str = "Standard_B2s",
    admin_username: str = "azureuser",
    os_type: str = "linux"
) -> str:
    """
    Deploy a new Azure Virtual Machine with networking
    
    Args:
        resource_group: Resource group name (will be created if doesn't exist)
        vm_name: Name for the virtual machine
        admin_password: Administrator password (min 12 chars, must include uppercase, lowercase, number, special char)
        location: Azure region (e.g., eastus, westus2, centralindia)
        vm_size: VM size (e.g., Standard_B2s, Standard_D2s_v3)
        admin_username: Administrator username
        os_type: Operating system type (linux or windows)
        
    Returns:
        Deployment result message
    """
    if not azure_creds:
        return "❌ Error: Azure credentials not initialized"
        
    if not admin_password:
        return "❌ Error: admin_password is required"
        
    if os_type not in ["linux", "windows"]:
        return "❌ Error: os_type must be 'linux' or 'windows'"
    
    try:
        # Step 1: Create Resource Group
        logger.info(f"Creating resource group: {resource_group}")
        azure_creds.resource_client.resource_groups.create_or_update(
            resource_group,
            {"location": location}
        )
        
        # Step 2: Create Virtual Network
        vnet_name = f"{vm_name}-vnet"
        logger.info(f"Creating virtual network: {vnet_name}")
        
        vnet_params = {
            "location": location,
            "address_space": {
                "address_prefixes": ["10.0.0.0/16"]
            }
        }
        
        vnet_result = azure_creds.network_client.virtual_networks.begin_create_or_update(
            resource_group,
            vnet_name,
            vnet_params
        ).result()
        
        # Step 3: Create Subnet
        subnet_name = f"{vm_name}-subnet"
        logger.info(f"Creating subnet: {subnet_name}")
        
        subnet_params = {
            "address_prefix": "10.0.0.0/24"
        }
        
        subnet_result = azure_creds.network_client.subnets.begin_create_or_update(
            resource_group,
            vnet_name,
            subnet_name,
            subnet_params
        ).result()
        
        # Step 4: Create Public IP Address
        public_ip_name = f"{vm_name}-ip"
        logger.info(f"Creating public IP: {public_ip_name}")
        
        public_ip_params = {
            "location": location,
            "sku": {"name": "Standard"},
            "public_ip_allocation_method": "Static",
            "public_ip_address_version": "IPv4"
        }
        
        public_ip_result = azure_creds.network_client.public_ip_addresses.begin_create_or_update(
            resource_group,
            public_ip_name,
            public_ip_params
        ).result()
        
        # Step 5: Create Network Interface
        nic_name = f"{vm_name}-nic"
        logger.info(f"Creating network interface: {nic_name}")
        
        nic_params = {
            "location": location,
            "ip_configurations": [{
                "name": "ipconfig1",
                "subnet": {"id": subnet_result.id},
                "public_ip_address": {"id": public_ip_result.id}
            }]
        }
        
        nic_result = azure_creds.network_client.network_interfaces.begin_create_or_update(
            resource_group,
            nic_name,
            nic_params
        ).result()
        
        # Step 6: Define OS Profile
        if os_type == "linux":
            image_reference = {
                "publisher": "Canonical",
                "offer": "0001-com-ubuntu-server-jammy",
                "sku": "22_04-lts-gen2",
                "version": "latest"
            }
        else:  # windows
            image_reference = {
                "publisher": "MicrosoftWindowsServer",
                "offer": "WindowsServer",
                "sku": "2022-datacenter-azure-edition",
                "version": "latest"
            }
        
        # Step 7: Create Virtual Machine
        logger.info(f"Creating virtual machine: {vm_name}")
        
        vm_params = {
            "location": location,
            "hardware_profile": {
                "vm_size": vm_size
            },
            "storage_profile": {
                "image_reference": image_reference,
                "os_disk": {
                    "create_option": "FromImage",
                    "managed_disk": {
                        "storage_account_type": "Premium_LRS"
                    }
                }
            },
            "os_profile": {
                "computer_name": vm_name,
                "admin_username": admin_username,
                "admin_password": admin_password
            },
            "network_profile": {
                "network_interfaces": [{
                    "id": nic_result.id,
                    "properties": {
                        "primary": True
                    }
                }]
            }
        }
        
        vm_result = azure_creds.compute_client.virtual_machines.begin_create_or_update(
            resource_group,
            vm_name,
            vm_params
        ).result()
        
        # Get public IP address
        public_ip = azure_creds.network_client.public_ip_addresses.get(
            resource_group,
            public_ip_name
        )
        
        success_msg = f"""✅ Virtual Machine deployed successfully!

VM Details:
- Name: {vm_name}
- Resource Group: {resource_group}
- Location: {location}
- Size: {vm_size}
- OS: {os_type}
- Public IP: {public_ip.ip_address}
- Admin Username: {admin_username}

Resources Created:
- Virtual Machine: {vm_name}
- Network Interface: {nic_name}
- Public IP: {public_ip_name}
- Virtual Network: {vnet_name}
- Subnet: {subnet_name}

Connection Info:"""
        
        if os_type == "linux":
            success_msg += f"\n  ssh {admin_username}@{public_ip.ip_address}"
        else:
            success_msg += f"\n  RDP to {public_ip.ip_address}"
        
        return success_msg
        
    except Exception as e:
        error_msg = f"❌ Failed to deploy VM '{vm_name}': {str(e)}"
        logger.error(f"Failed to deploy VM '{vm_name}': {str(e)}")
        return error_msg

@app.tool()
async def restart_service(
    resource_group: str,
    vm_name: str,
    service_name: str,
    os_type: str = "windows"
) -> str:
    """
    Restart a service inside an Azure VM (like Tomcat, SQL Server, IIS, nginx, etc.)
    
    Args:
        resource_group: Resource group containing the VM
        vm_name: Name of the virtual machine
        service_name: Name of the service to restart (e.g., 'tomcat', 'MSSQLSERVER', 'nginx')
        os_type: Operating system type - 'windows' or 'linux' (default: windows)
        
    Returns:
        Result of the service restart operation
    """
    if not azure_creds:
        return "❌ Error: Azure credentials not initialized"
        
    if not resource_group or not vm_name or not service_name:
        return "❌ Error: resource_group, vm_name, and service_name are required"
    
    if os_type.lower() not in ["windows", "linux"]:
        return "❌ Error: os_type must be 'windows' or 'linux'"
    
    try:
        logger.info(f"Restarting service '{service_name}' on VM: {vm_name}")
        
        # Build appropriate command based on OS type
        if os_type.lower() == "windows":
            # Windows PowerShell command
            script = f"""
$serviceName = "{service_name}"

Write-Host "=== SERVICE RESTART ==="
Write-Host "Service: $serviceName"
Write-Host "VM: {vm_name}"
Write-Host ""

# Check if service exists
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if ($null -eq $service) {{
    Write-Host "❌ Service '$serviceName' not found on this VM"
    Write-Host ""
    Write-Host "Available services:"
    Get-Service | Where-Object {{ $_.Status -eq 'Running' }} | Select-Object -First 10 Name, DisplayName | Format-Table -AutoSize
    exit 1
}}

Write-Host "Current status: $($service.Status)"
Write-Host ""

# Restart the service
try {{
    Write-Host "🔄 Restarting service..."
    Restart-Service -Name $serviceName -Force -ErrorAction Stop
    Start-Sleep -Seconds 2
    
    # Verify service is running
    $service = Get-Service -Name $serviceName
    
    if ($service.Status -eq 'Running') {{
        Write-Host "✅ Service restarted successfully!"
        Write-Host "New status: $($service.Status)"
    }} else {{
        Write-Host "⚠️  Service restarted but status is: $($service.Status)"
    }}
}} catch {{
    Write-Host "❌ Failed to restart service: $($_.Exception.Message)"
    exit 1
}}
"""
            command_id = "RunPowerShellScript"
        else:
            # Linux bash command
            script = f"""
#!/bin/bash

SERVICE_NAME="{service_name}"

echo "=== SERVICE RESTART ==="
echo "Service: $SERVICE_NAME"
echo "VM: {vm_name}"
echo ""

# Check if service exists
if ! systemctl list-units --type=service --all | grep -q "$SERVICE_NAME.service"; then
    echo "❌ Service '$SERVICE_NAME' not found on this VM"
    echo ""
    echo "Available services:"
    systemctl list-units --type=service --state=running | head -n 15
    exit 1
fi

# Get current status
echo "Current status:"
systemctl status $SERVICE_NAME --no-pager | head -n 5
echo ""

# Restart the service
echo "🔄 Restarting service..."
if systemctl restart $SERVICE_NAME; then
    sleep 2
    
    # Verify service is running
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo "✅ Service restarted successfully!"
        echo "New status:"
        systemctl status $SERVICE_NAME --no-pager | head -n 5
    else
        echo "⚠️  Service restarted but may not be running properly"
        systemctl status $SERVICE_NAME --no-pager | head -n 10
    fi
else
    echo "❌ Failed to restart service"
    systemctl status $SERVICE_NAME --no-pager
    exit 1
fi
"""
            command_id = "RunShellScript"
        
        # Execute the command via Azure Run Command
        run_command_result = azure_creds.compute_client.virtual_machines.begin_run_command(
            resource_group,
            vm_name,
            {
                "command_id": command_id,
                "script": [script]
            }
        ).result()
        
        # Extract output
        output = ""
        error_output = ""
        
        if run_command_result.value:
            for result in run_command_result.value:
                if result.code == "ComponentStatus/StdOut/succeeded":
                    output += result.message or ""
                elif result.code == "ComponentStatus/StdErr/succeeded":
                    error_output += result.message or ""
        
        # Determine success based on output
        if output and ("✅" in output or "successfully" in output.lower()):
            return f"✅ Service Restart Completed for '{service_name}' on VM '{vm_name}':\n\n{output}"
        elif "❌" in output or error_output:
            return f"❌ Service Restart Failed for '{service_name}' on VM '{vm_name}':\n\n{output}\n{error_output if error_output else ''}"
        else:
            return f"⚠️  Service Restart Status for '{service_name}' on VM '{vm_name}':\n\n{output}"
        
    except Exception as e:
        error_msg = f"❌ Failed to restart service '{service_name}' on VM '{vm_name}': {str(e)}"
        logger.error(f"Failed to restart service '{service_name}' on VM '{vm_name}': {str(e)}")
        return error_msg


@app.tool()
async def get_process_utilization(
    resource_group: str,
    vm_name: str,
    os_type: str = "windows",
    sample_seconds: int = 5,
    top_n: int = 15
) -> str:
    """
    Get top CPU and Memory consuming processes on an Azure VM
    
    Args:
        resource_group: Resource group containing the VM
        vm_name: Name of the virtual machine
        os_type: Operating system type - 'windows' or 'linux' (default: windows)
        sample_seconds: Sampling period in seconds (default: 5)
        top_n: Number of top processes to return (default: 15)
        
    Returns:
        JSON string with process utilization data
    """
    if not azure_creds:
        return json.dumps({"error": "Azure credentials not initialized", "success": False})
        
    if not resource_group or not vm_name:
        return json.dumps({"error": "resource_group and vm_name are required", "success": False})
    
    if os_type.lower() not in ["windows", "linux"]:
        return json.dumps({"error": "os_type must be 'windows' or 'linux'", "success": False})
    
    try:
        logger.info(f"Getting process utilization for VM: {vm_name}")
        
        # Build appropriate script based on OS type
        if os_type.lower() == "windows":
            # Windows PowerShell script
            script = f"""
$SampleSeconds = {sample_seconds}
$TopN = {top_n}

# Step 1: First snapshot
$proc1 = Get-Process | Select-Object Id, Name, CPU, WorkingSet64

Start-Sleep -Seconds $SampleSeconds

# Step 2: Second snapshot
$proc2 = Get-Process | Select-Object Id, Name, CPU, WorkingSet64

# Step 3: System resource details
$cpuCount = (Get-WmiObject Win32_ComputerSystem).NumberOfLogicalProcessors
$totalMem = (Get-WmiObject Win32_OperatingSystem).TotalVisibleMemorySize * 1KB

# Step 4: Compute CPU & Memory%
$result = foreach ($p2 in $proc2) {{
    $p1 = $proc1 | Where-Object {{ $_.Id -eq $p2.Id }}
    if ($p1 -and $p2.CPU -ne $null) {{
        $cpuDelta = ($p2.CPU - $p1.CPU)
        $cpuPct = [math]::Round(($cpuDelta / $SampleSeconds / $cpuCount) * 100, 2)
        $memPct = [math]::Round(($p2.WorkingSet64 / $totalMem) * 100, 2)
        [PSCustomObject]@{{
            process_name = $p2.Name
            pid = $p2.Id
            cpu_percent = $cpuPct
            memory_mb = [math]::Round($p2.WorkingSet64 / 1MB, 2)
            memory_percent = $memPct
        }}
    }}
}}

# Step 5: Output as JSON
$output = @{{
    success = $true
    vm_name = "{vm_name}"
    os_type = "windows"
    sample_seconds = $SampleSeconds
    cpu_cores = $cpuCount
    total_memory_gb = [math]::Round($totalMem / 1GB, 2)
    processes = @($result | Sort-Object -Property cpu_percent -Descending | Select-Object -First $TopN)
}}

$output | ConvertTo-Json -Depth 3
"""
            command_id = "RunPowerShellScript"
        else:
            # Linux bash script
            script = f"""
#!/bin/bash

SAMPLE_SECONDS={sample_seconds}
TOP_N={top_n}

# Get CPU cores
CPU_CORES=$(nproc)

# Get total memory in bytes
TOTAL_MEM=$(grep MemTotal /proc/meminfo | awk '{{print $2 * 1024}}')
TOTAL_MEM_GB=$(echo "scale=2; $TOTAL_MEM / 1024 / 1024 / 1024" | bc)

# Function to get process stats
get_proc_stats() {{
    ps -eo pid,comm,pcpu,pmem,rss --sort=-pcpu | tail -n +2
}}

# First snapshot
PROC1=$(get_proc_stats)

sleep $SAMPLE_SECONDS

# Second snapshot
PROC2=$(get_proc_stats)

# Build JSON output
echo '{{
  "success": true,
  "vm_name": "{vm_name}",
  "os_type": "linux",
  "sample_seconds": '$SAMPLE_SECONDS',
  "cpu_cores": '$CPU_CORES',
  "total_memory_gb": '$TOTAL_MEM_GB',
  "processes": ['

# Parse top N processes
FIRST=true
echo "$PROC2" | head -n $TOP_N | while IFS= read -r line; do
    PID=$(echo $line | awk '{{print $1}}')
    PNAME=$(echo $line | awk '{{print $2}}')
    CPU=$(echo $line | awk '{{print $3}}')
    MEM_PCT=$(echo $line | awk '{{print $4}}')
    RSS=$(echo $line | awk '{{print $5}}')
    MEM_MB=$(echo "scale=2; $RSS / 1024" | bc)
    
    if [ "$FIRST" = false ]; then
        echo ','
    fi
    FIRST=false
    
    echo '    {{'
    echo '      "process_name": "'$PNAME'",'
    echo '      "pid": '$PID','
    echo '      "cpu_percent": '$CPU','
    echo '      "memory_mb": '$MEM_MB','
    echo '      "memory_percent": '$MEM_PCT
    echo '    }}'
done

echo '
  ]
}}'
"""
            command_id = "RunShellScript"
        
        # Execute the command via Azure Run Command
        run_command_result = azure_creds.compute_client.virtual_machines.begin_run_command(
            resource_group,
            vm_name,
            {
                "command_id": command_id,
                "script": [script]
            }
        ).result()
        
        # Extract output
        output = ""
        error_output = ""
        
        if run_command_result.value:
            for result in run_command_result.value:
                if result.code == "ComponentStatus/StdOut/succeeded":
                    output += result.message or ""
                elif result.code == "ComponentStatus/StdErr/succeeded":
                    error_output += result.message or ""
        
        # Try to parse and return JSON output
        if output:
            try:
                # Validate JSON
                json_data = json.loads(output)
                return json.dumps(json_data, indent=2)
            except json.JSONDecodeError:
                # If not valid JSON, wrap it
                return json.dumps({
                    "success": False,
                    "error": "Failed to parse output as JSON",
                    "raw_output": output,
                    "error_output": error_output
                })
        else:
            return json.dumps({
                "success": False,
                "error": "No output received from VM",
                "error_output": error_output
            })
        
    except Exception as e:
        error_msg = {"success": False, "error": f"Failed to get process utilization: {str(e)}"}
        logger.error(f"Failed to get process utilization for VM '{vm_name}': {str(e)}")
        return json.dumps(error_msg)


@app.tool()
async def restart_vm(resource_group: str, vm_name: str) -> str:
    """
    Restart an existing Azure Virtual Machine
    
    Args:
        resource_group: Resource group containing the VM
        vm_name: Name of the virtual machine to restart
        
    Returns:
        Operation result message
    """
    if not azure_creds:
        return "❌ Error: Azure credentials not initialized"
        
    if not resource_group or not vm_name:
        return "❌ Error: Both 'resource_group' and 'vm_name' are required"
    
    try:
        # Verify VM exists
        logger.info(f"Verifying VM exists: {vm_name}")
        vm = azure_creds.compute_client.virtual_machines.get(
            resource_group,
            vm_name
        )
        
        # Initiate restart operation
        logger.info(f"Restarting VM: {vm_name}")
        restart_operation = azure_creds.compute_client.virtual_machines.begin_restart(
            resource_group,
            vm_name
        )
        
        # Wait for operation to complete
        restart_operation.result()
        
        return f"✅ Successfully restarted VM '{vm_name}' in resource group '{resource_group}'"
        
    except Exception as e:
        error_msg = f"❌ Failed to restart VM '{vm_name}': {str(e)}"
        logger.error(f"Failed to restart VM '{vm_name}': {str(e)}")
        return error_msg


async def run_stdio():
    """Run the MCP server with stdio transport"""
    logger.info("Starting Custom Azure MCP Server (stdio)...")
    logger.info(f"Subscription: {azure_creds.subscription_id if azure_creds else 'Not initialized'}")
    await app.run_stdio_async()


async def run_http(host: str = "localhost", port: int = 8000):
    """Run the MCP server with HTTP transport"""
    logger.info(f"Starting Custom Azure MCP Server (HTTP) on {host}:{port}...")
    logger.info(f"Subscription: {azure_creds.subscription_id if azure_creds else 'Not initialized'}")
    
    # Create new FastMCP instance with proper host/port
    http_app = FastMCP(name="custom-azure-mcp", host=host, port=port)
    
    # Register the same tools on the HTTP app
    http_app.add_tool(deploy_vm)
    http_app.add_tool(restart_service)
    http_app.add_tool(get_process_utilization)
    http_app.add_tool(restart_vm)
    
    # Run with streamable HTTP transport
    await http_app.run_streamable_http_async()


def main():
    global azure_creds
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Azure MCP Server')
    parser.add_argument('--transport', choices=['stdio', 'http'], 
                       default='stdio', help='Transport protocol (default: stdio)')
    parser.add_argument('--host', default='localhost', 
                       help='HTTP host (ignored for stdio, default: localhost)')
    parser.add_argument('--port', type=int, default=8000, 
                       help='HTTP port (ignored for stdio, default: 8000)')
    
    args = parser.parse_args()
    
    # Get Azure credentials from environment variables
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        # For missing credentials, we can safely print to stderr as this happens before MCP starts
        print("Error: Missing required environment variables:", file=sys.stderr)
        print("  - AZURE_TENANT_ID", file=sys.stderr)
        print("  - AZURE_CLIENT_ID", file=sys.stderr)
        print("  - AZURE_CLIENT_SECRET", file=sys.stderr)
        print("  - AZURE_SUBSCRIPTION_ID", file=sys.stderr)
        sys.exit(1)
    
    # Configure logging based on transport
    if args.transport == 'http':
        # For HTTP transport, we can safely add console logging
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)
    
    # Initialize Azure credentials
    azure_creds = AzureCredentials(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        subscription_id=subscription_id
    )
    
    # Run server with selected transport
    try:
        if args.transport == 'stdio':
            asyncio.run(run_stdio())
        else:  # http
            asyncio.run(run_http(host=args.host, port=args.port))
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        if args.transport == 'http':
            print("\nShutting down...", file=sys.stderr)  # Safe for HTTP transport


if __name__ == "__main__":
    main()