# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is an Azure MCP (Model Context Protocol) server project that provides programmatic access to Azure resources through the MCP protocol. The project is built in Python and uses Azure SDK packages for cloud resource management.

## Environment Setup

### Virtual Environment
The project uses a Python virtual environment located in `.venv/` with Python 3.10.18.

**Activate virtual environment:**
```powershell
.venv\Scripts\Activate.ps1
```

**Install dependencies:**
```powershell
pip install -r requirements.txt
```

### Environment Variables
The project requires Azure service principal credentials. These are configured in `.env`:
- `AZURE_SUBSCRIPTION_ID` - Azure subscription identifier
- `AZURE_TENANT_ID` - Azure AD tenant identifier  
- `AZURE_CLIENT_ID` - Service principal client ID
- `AZURE_CLIENT_SECRET` - Service principal client secret

**Verify environment setup:**
```powershell
python test.py
```

## Development Commands

### Testing Dependencies
```powershell
python test.py
```
Verifies that all required packages are installed and environment variables are configured.

### Running the MCP Server
```powershell
python custom_azure_mcp.py
```
Starts the MCP server with stdio communication for Azure operations.

### Development Testing
```powershell
# Test VM deployment (example)
# Requires MCP client to call tools - server runs via stdio
```

## Architecture

### Core Dependencies
- **MCP SDK** (`mcp>=1.0.0`) - Model Context Protocol implementation
- **Azure Identity** (`azure-identity>=1.15.0`) - Azure authentication
- **Azure Management SDKs** - For compute, network, and resource management
- **aiohttp** (`>=3.9.0`) - Async HTTP support for MCP operations
- **python-dotenv** - Environment variable loading

### Key Files
- `custom_azure_mcp.py` - Main MCP server implementation with modular architecture
- `test.py` - Environment and dependency verification script
- `requirements.txt` - Python package dependencies
- `.env` - Azure authentication configuration

### Implementation Architecture

#### Modular Design
- **CustomAzureMCPServer** - Main server orchestrator
- **VirtualMachineManager** - Handles all VM operations
- Future modules planned for disk management, storage operations

#### Available MCP Tools

**Virtual Machine Operations:**
- `deploy_vm` - Deploy new VM with full networking stack (VNet, subnet, public IP, NIC)
  - Required: `resource_group`, `vm_name`, `admin_password`
  - Optional: `location` (default: eastus), `vm_size` (default: Standard_B2s), `admin_username` (default: azureuser), `os_type` (default: linux)
  - Supports: Linux (Ubuntu 22.04), Windows (Server 2022)
- `restart_vm` - Restart existing virtual machines
  - Required: `resource_group`, `vm_name`

#### VM Deployment Features
- Automatic resource group creation
- Complete networking setup (VNet, subnet, public IP, network interface)
- Support for Linux (Ubuntu 22.04) and Windows Server 2022
- Configurable VM sizes and locations
- Premium SSD storage by default
- Public IP assignment for remote access

#### Communication
- Uses stdio for MCP client communication
- Async operations for all Azure API calls
- Detailed logging to stderr for debugging
- Structured error handling with user-friendly messages

## Extending the Server

### Adding New Resource Managers
1. Create new manager class (e.g., `DiskManager`, `StorageManager`)
2. Implement `get_tools()` method returning list of `Tool` objects
3. Add async methods for each tool operation
4. Register manager in `CustomAzureMCPServer._setup_handlers()`
5. Add tool routing in the `call_tool()` handler

### Tool Implementation Pattern
- Each tool has clear input schema with required/optional parameters
- Async methods return `List[TextContent]` with operation results
- Error handling with user-friendly messages and stderr logging
- Success messages include relevant resource details

## Security Notes
- Azure credentials are stored in `.env` - ensure this file is never committed
- Service principal should follow principle of least privilege
- All Azure operations should use proper authentication flows
- Password parameters should meet Azure complexity requirements (12+ chars, mixed case, numbers, special chars)
