import platform

try:
    from importlib import metadata
    package_version = metadata.version("e2b")
except Exception:
    package_version = "0.0.1-embedded"

default_headers = {
    "lang": "python",
    "lang_version": platform.python_version(),
    "package_version": package_version,
    "publisher": "e2b",
    "sdk_runtime": "python",
    "system": platform.system(),
}
