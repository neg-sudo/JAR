"""Version and product metadata for JAR."""

APP_NAME = "JAR"
APP_TAGLINE = "Just Automated Routing"
__version__ = "2.0.0"

# Kept in one place so the CLI, GUI, packaging and tests never drift apart.
VERSION_INFO = tuple(int(part) for part in __version__.split("."))
