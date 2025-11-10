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

**stdio mode (default):**
```powershell
python custom_azure_mcp.py
# or explicitly
python custom_azure_mcp.py --transport stdio
```

**HTTP mode:**
```powershell
# Default (localhost:8000)
python custom_azure_mcp.py --transport http

# Custom host/port
python custom_azure_mcp.py --transport http --host 0.0.0.0 --port 8001
```

### Development Testing
```powershell
# Test server startup
python custom_azure_mcp.py --help

# Test HTTP server (accessible via browser/curl at http://localhost:8000)
python custom_azure_mcp.py --transport http
```

### Logging
The server uses Python logging to avoid interfering with MCP stdio communication:
- **Log file**: `azure_mcp_server.log` (always created)
- **Console logging**: Only enabled for HTTP transport
- **stdio transport**: Logs only to file to prevent MCP protocol interference

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

#### Core Design
- **FastMCP-based** - Uses MCP SDK's FastMCP class for dual transport support
- **Global Azure credentials** - Shared authentication across all tools
- **Decorator-based tools** - Each Azure operation is a `@app.tool()` decorated function
- **Dual transport** - Same tools work with both stdio and HTTP transports

#### Available MCP Tools

**Virtual Machine Operations:**
- `deploy_vm` - Deploy new VM with full networking stack (VNet, subnet, public IP, NIC)
  - Required: `resource_group`, `vm_name`, `admin_password`
  - Optional: `location` (default: eastus), `vm_size` (default: Standard_B2s), `admin_username` (default: azureuser), `os_type` (default: linux)
  - Supports: Linux (Ubuntu 22.04), Windows (Server 2022)
- `restart_service` - Restart a service inside a running VM (Tomcat, SQL Server, IIS, nginx, etc.)
  - Required: `resource_group`, `vm_name`, `service_name`
  - Optional: `os_type` (default: windows) - windows or linux
  - Uses Azure Run Command to execute restart inside the VM
  - Verifies service status after restart
- `restart_vm` - Restart entire virtual machine
  - Required: `resource_group`, `vm_name`

#### VM Deployment Features
- Automatic resource group creation
- Complete networking setup (VNet, subnet, public IP, network interface)
- Support for Linux (Ubuntu 22.04) and Windows Server 2022
- Configurable VM sizes and locations
- Premium SSD storage by default
- Public IP assignment for remote access

#### Communication
- **Dual transport**: stdio (for IDE integration) or HTTP (for web clients)
- **stdio**: Direct process communication via stdin/stdout
- **HTTP**: RESTful API on configurable host/port with streamable HTTP transport
- Async operations for all Azure API calls
- Detailed logging to stderr for debugging
- Structured error handling with user-friendly messages

## Extending the Server

### Adding New Tools (FastMCP Pattern)
1. Create new async function with proper type hints
2. Add `@app.tool()` decorator
3. Include comprehensive docstring describing the tool
4. For HTTP transport, register tool with `http_app.add_tool(your_function)`
5. Return string results (not TextContent objects)

### Tool Implementation Pattern
- Use `@app.tool()` decorator on async functions
- Function parameters become tool input schema automatically
- Use type hints for parameter validation
- Return strings (success/error messages)
- Access global `azure_creds` for Azure operations
- Log progress to stderr for debugging

## Security Notes
- Azure credentials are stored in `.env` - ensure this file is never committed
- Service principal should follow principle of least privilege
- All Azure operations should use proper authentication flows
- Password parameters should meet Azure complexity requirements (12+ chars, mixed case, numbers, special chars)
