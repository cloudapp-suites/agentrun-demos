"""Execute code in a self-hosted E2B sandbox."""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from e2b import Sandbox

_LANG_CMD = {
    "python": "python3 -c",
    "javascript": "node -e",
    "shell": "bash -c",
}


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


class ExecuteCodeTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            yield from self._do_invoke(tool_parameters)
        except Exception as e:
            yield self.create_text_message(f"Error: {type(e).__name__}: {e}")
            yield self.create_json_message({
                "error": str(e),
                "error_type": type(e).__name__,
                "tool_parameters_keys": list(tool_parameters.keys()),
                "tool_parameters": {k: repr(v)[:100] for k, v in tool_parameters.items()},
            })

    def _do_invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        # Get code - try every possible way
        code = tool_parameters.get("code")
        if not code:
            code = tool_parameters.get("代码")
        if not code:
            for k, v in tool_parameters.items():
                if isinstance(v, str) and len(v) > 10 and k not in ("language", "template_id", "timeout"):
                    code = v
                    break
        if not code:
            yield self.create_text_message(
                f"Missing 'code' parameter. Received: {list(tool_parameters.keys())}. "
                f"Values: {tool_parameters}"
            )
            return

        language = tool_parameters.get("language", "python")
        timeout = 300
        try:
            timeout = int(tool_parameters.get("timeout", 300))
        except (TypeError, ValueError):
            pass

        template_id = (
            tool_parameters.get("template_id")
            or self.runtime.credentials.get("default_template")
            or "base"
        )
        api_url = self.runtime.credentials.get("api_url", "")
        sandbox_url = self.runtime.credentials.get("sandbox_url", "")
        api_key = self.runtime.credentials.get("api_key", "")

        sandbox = Sandbox.create(
            template=template_id,
            timeout=timeout,
            api_url=api_url,
            sandbox_url=sandbox_url,
            api_key=api_key,
        )

        try:
            cmd_prefix = _LANG_CMD.get(language, "bash -c")
            result = sandbox.commands.run(
                f"{cmd_prefix} {_shell_quote(code)}", timeout=timeout
            )
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
