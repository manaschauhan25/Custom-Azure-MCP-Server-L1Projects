#!/usr/bin/env python3
"""
Custom Azure MCP Server
Modular architecture with separate resource classes
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server.fastmcp import fastapi_app
import uvicorn
from dotenv import load_dotenv

import argparse



# Load environment variables
load_dotenv()

class VirtualMachineManager:
    """Manages Azure Virtual Machine operations"""
    
    def __init__(
        self,
        compute_client: ComputeManagementClient,
        network_client: NetworkManagementClient,
        resource_client: ResourceManagementClient
    ):
        self.compute_client = compute_client
        self.network_client = network_client
        self.resource_client = resource_client

    def get_tools(self) -> List[Tool]:
        """Return list of VM-related tools"""
        return [
            Tool(
                name="deploy_vm",
                description="Deploy a new Azure Virtual Machine with networking",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "resource_group": {
                            "type": "string",
                            "description": "Resource group name (will be created if doesn't exist)"
                        },
                        "vm_name": {
                            "type": "string",
                            "description": "Name for the virtual machine"
                        },
                        "location": {
                            "type": "string",
                            "description": "Azure region (e.g., eastus, westus2, centralindia)",
                            "default": "eastus"
                        },
                        "vm_size": {
                            "type": "string",
                            "description": "VM size (e.g., Standard_B2s, Standard_D2s_v3)",
                            "default": "Standard_B2s"
                        },
                        "admin_username": {
                            "type": "string",
                            "description": "Administrator username",
                            "default": "azureuser"
                        },
                        "admin_password": {
                            "type": "string",
                            "description": "Administrator password (min 12 chars, must include uppercase, lowercase, number, special char)"
                        },
                        "os_type": {
                            "type": "string",
                            "enum": ["linux", "windows"],
                            "description": "Operating system type",
                            "default": "linux"
                        }
                    },
                    "required": ["resource_group", "vm_name", "admin_password"]
                }
            ),
            Tool(
                name="restart_vm",
                description="Restart an existing Azure Virtual Machine",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "resource_group": {
                            "type": "string",
                            "description": "Resource group containing the VM"
                        },
                        "vm_name": {
                            "type": "string",
                            "description": "Name of the virtual machine to restart"
                        }
                    },
                    "required": ["resource_group", "vm_name"]
                }
            )
        ]

    async def deploy_vm(self, args: Dict[str, Any]) -> List[TextContent]:
        """
        Deploy a new Azure Virtual Machine
        
        Args:
            args: Dictionary with deployment parameters
            
        Returns:
            List of TextContent with deployment result
        """
        resource_group = args.get("resource_group")
        vm_name = args.get("vm_name")
        location = args.get("location", "eastus")
        vm_size = args.get("vm_size", "Standard_B2s")
        admin_username = args.get("admin_username", "azureuser")
        admin_password = args.get("admin_password")
        os_type = args.get("os_type", "linux")
        
        if not admin_password:
            return [TextContent(
                type="text",
                text="Error: admin_password is required"
            )]
        
        try:
            # Step 1: Create Resource Group
            print(f"Creating resource group: {resource_group}", file=sys.stderr)
            self.resource_client.resource_groups.create_or_update(
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
            
            vnet_result = self.network_client.virtual_networks.begin_create_or_update(
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
            
            subnet_result = self.network_client.subnets.begin_create_or_update(
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
            
            public_ip_result = self.network_client.public_ip_addresses.begin_create_or_update(
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
            
            nic_result = self.network_client.network_interfaces.begin_create_or_update(
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
            
            vm_result = self.compute_client.virtual_machines.begin_create_or_update(
                resource_group,
                vm_name,
                vm_params
            ).result()
            
            # Get public IP address
            public_ip = self.network_client.public_ip_addresses.get(
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

Connection Info:
"""
            
            if os_type == "linux":
                success_msg += f"  ssh {admin_username}@{public_ip.ip_address}"
            else:
                success_msg += f"  RDP to {public_ip.ip_address}"
            
            return [TextContent(type="text", text=success_msg)]
            
        except Exception as e:
            error_msg = f"❌ Failed to deploy VM '{vm_name}': {str(e)}"
            print(error_msg, file=sys.stderr)
            return [TextContent(type="text", text=error_msg)]

    async def restart_vm(self, args: Dict[str, Any]) -> List[TextContent]:
        """
        Restart an Azure Virtual Machine
        
        Args:
            args: Dictionary containing 'resource_group' and 'vm_name'
        
        Returns:
            List of TextContent with operation result
        """
        resource_group = args.get("resource_group")
        vm_name = args.get("vm_name")
        
        if not resource_group or not vm_name:
            return [TextContent(
                type="text",
                text="Error: Both 'resource_group' and 'vm_name' are required"
            )]
        
        try:
            # Verify VM exists
            print(f"Verifying VM exists: {vm_name}", file=sys.stderr)
            vm = self.compute_client.virtual_machines.get(
                resource_group,
                vm_name
            )
            
            # Initiate restart operation
            print(f"Restarting VM: {vm_name}", file=sys.stderr)
            restart_operation = self.compute_client.virtual_machines.begin_restart(
                resource_group,
                vm_name
            )
            
            # Wait for operation to complete
            restart_operation.result()
            
            success_msg = f"✅ Successfully restarted VM '{vm_name}' in resource group '{resource_group}'"
            return [TextContent(type="text", text=success_msg)]
            
        except Exception as e:
            error_msg = f"❌ Failed to restart VM '{vm_name}': {str(e)}"
            print(error_msg, file=sys.stderr)
            return [TextContent(type="text", text=error_msg)]


class CustomAzureMCPServer:
    """Main MCP Server orchestrating all resource managers"""
    
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        subscription_id: str
    ):
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
        self.compute_client = ComputeManagementClient(
            self.credential,
            subscription_id
        )
        self.network_client = NetworkManagementClient(
            self.credential,
            subscription_id
        )
        self.resource_client = ResourceManagementClient(
            self.credential,
            subscription_id
        )
        
        # Initialize resource managers
        self.vm_manager = VirtualMachineManager(
            self.compute_client,
            self.network_client,
            self.resource_client
        )
        
        # Initialize MCP server
        self.server = Server("custom-azure-mcp")
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup MCP server handlers for tools"""
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """List all available tools from all resource managers"""
            tools = []
            
            # Add VM tools
            tools.extend(self.vm_manager.get_tools())
            
            # Future: Add disk tools
            # tools.extend(self.disk_manager.get_tools())
            
            # Future: Add storage tools
            # tools.extend(self.storage_manager.get_tools())
            
            return tools
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Route tool calls to appropriate resource manager"""
            
            # VM tools
            if name == "deploy_vm":
                return await self.vm_manager.deploy_vm(arguments)
            elif name == "restart_vm":
                return await self.vm_manager.restart_vm(arguments)
            
            # Future: Disk tools
            # elif name == "create_disk":
            #     return await self.disk_manager.create_disk(arguments)
            
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def run(self):
        """Run the custom MCP server"""
        print("Starting Custom Azure MCP Server...", file=sys.stderr)
        print(f"Subscription: {self.subscription_id}", file=sys.stderr)
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Main entry point"""
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
    
    # Create and run server
    server = CustomAzureMCPServer(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        subscription_id=subscription_id
    )
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)


if __name__ == "__main__":
    main()