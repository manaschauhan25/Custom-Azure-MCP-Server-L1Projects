#!/usr/bin/env python3
"""
Custom Azure MCP Server
Dual-transport architecture supporting both stdio and HTTP
"""

import argparse
import asyncio
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
        print(f"Creating resource group: {resource_group}", file=sys.stderr)
        azure_creds.resource_client.resource_groups.create_or_update(
            resource_group,
            {"location": location}
        )
        
        # Step 2: Create Virtual Network
        vnet_name = f"{vm_name}-vnet"
        print(f"Creating virtual network: {vnet_name}", file=sys.stderr)
        
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
        print(f"Creating subnet: {subnet_name}", file=sys.stderr)
        
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
        print(f"Creating public IP: {public_ip_name}", file=sys.stderr)
        
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
        print(f"Creating network interface: {nic_name}", file=sys.stderr)
        
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
        print(f"Creating virtual machine: {vm_name}", file=sys.stderr)
        
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
        print(error_msg, file=sys.stderr)
        return error_msg

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
        print(f"Verifying VM exists: {vm_name}", file=sys.stderr)
        vm = azure_creds.compute_client.virtual_machines.get(
            resource_group,
            vm_name
        )
        
        # Initiate restart operation
        print(f"Restarting VM: {vm_name}", file=sys.stderr)
        restart_operation = azure_creds.compute_client.virtual_machines.begin_restart(
            resource_group,
            vm_name
        )
        
        # Wait for operation to complete
        restart_operation.result()
        
        return f"✅ Successfully restarted VM '{vm_name}' in resource group '{resource_group}'"
        
    except Exception as e:
        error_msg = f"❌ Failed to restart VM '{vm_name}': {str(e)}"
        print(error_msg, file=sys.stderr)
        return error_msg


async def run_stdio():
    """Run the MCP server with stdio transport"""
    print("Starting Custom Azure MCP Server (stdio)...", file=sys.stderr)
    print(f"Subscription: {azure_creds.subscription_id if azure_creds else 'Not initialized'}", file=sys.stderr)
    await app.run_stdio_async()


async def run_http(host: str = "localhost", port: int = 8000):
    """Run the MCP server with HTTP transport"""
    print(f"Starting Custom Azure MCP Server (HTTP) on {host}:{port}...", file=sys.stderr)
    print(f"Subscription: {azure_creds.subscription_id if azure_creds else 'Not initialized'}", file=sys.stderr)
    
    # Create new FastMCP instance with proper host/port
    http_app = FastMCP(name="custom-azure-mcp", host=host, port=port)
    
    # Register the same tools on the HTTP app
    http_app.add_tool(deploy_vm)
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
        print("Error: Missing required environment variables:", file=sys.stderr)
        print("  - AZURE_TENANT_ID", file=sys.stderr)
        print("  - AZURE_CLIENT_ID", file=sys.stderr)
        print("  - AZURE_CLIENT_SECRET", file=sys.stderr)
        print("  - AZURE_SUBSCRIPTION_ID", file=sys.stderr)
        sys.exit(1)
    
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
        print("\nShutting down...", file=sys.stderr)


if __name__ == "__main__":
    main()