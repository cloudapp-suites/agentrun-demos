"""Dify plugin entrypoint for E2B Sandbox."""

from dify_plugin import Plugin, DifyPluginEnv

plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))
plugin.run()
