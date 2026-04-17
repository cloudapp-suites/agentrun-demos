"""E2B Sandbox provider — credential validation."""

from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from tools.execute_code import ExecuteCodeTool


class E2BSandboxProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """Validate credentials by creating a sandbox and running a trivial command."""
        try:
            for _ in ExecuteCodeTool.from_credentials(credentials).invoke(
                tool_parameters={"code": "print('ok')", "language": "python"},
            ):
                pass
        except Exception as e:
            raise ToolProviderCredentialValidationError(
                f"Failed to validate E2B sandbox credentials: {e}"
            )
