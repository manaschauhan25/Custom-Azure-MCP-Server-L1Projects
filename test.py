
import sys
print(f'Python version: {sys.version}')

try:
    import mcp
    print('✓ mcp installed')
except ImportError as e:
    print(f'✗ mcp missing: {e}')

try:
    import azure.identity
    print('✓ azure-identity installed')
except ImportError as e:
    print(f'✗ azure-identity missing: {e}')

import os
print(f'AZURE_TENANT_ID: {\"SET\" if os.getenv(\"AZURE_TENANT_ID\") else \"NOT SET\"}')
print(f'AZURE_CLIENT_ID: {\"SET\" if os.getenv(\"AZURE_CLIENT_ID\") else \"NOT SET\"}')
print(f'AZURE_CLIENT_SECRET: {\"SET\" if os.getenv(\"AZURE_CLIENT_SECRET\") else \"NOT SET\"}')
print(f'AZURE_SUBSCRIPTION_ID: {\"SET\" if os.getenv(\"AZURE_SUBSCRIPTION_ID\") else \"NOT SET\"}')
