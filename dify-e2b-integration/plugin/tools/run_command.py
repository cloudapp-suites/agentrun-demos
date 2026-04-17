"""Run a shell command in a self-hosted E2B sandbox."""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from e2b import Sandbox


class RunCommandTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            yield from self._do_invoke(tool_parameters)
        except Exception as e:
            yield self.create_text_message(f"Error: {type(e).__name__}: {e}")

    def _do_invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        command = tool_parameters.get("command", "")
        if not command:
            yield self.create_text_message("Missing 'command' parameter")
            return

        timeout = int(tool_parameters.get("timeout", 300))
        template_id = (
            tool_parameters.get("template_id")
            or self.runtime.credentials.get("default_template")
            or "base"
        )

        sandbox = Sandbox.create(
            template=template_id,
            timeout=timeout,
            api_url=self.runtime.credentials.get("api_url", ""),
            sandbox_url=self.runtime.credentials.get("sandbox_url", ""),
            api_key=self.runtime.credentials.get("api_key", ""),
        )

        try:
            result = sandbox.commands.run(command, timeout=timeout)
            yield self.create_text_message(result.stdout)
            yield self.create_json_message({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "success": result.exit_code == 0,
            })
        finally:
            try:
                sandbox.kill()
            except Exception:
                pass
