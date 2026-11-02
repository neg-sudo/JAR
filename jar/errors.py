"""Exception types used across JAR."""


class JarError(Exception):
    """Base class for expected, user-facing JAR errors."""


class ConfigError(JarError):
    """Raised when configuration cannot be loaded, parsed or validated."""


class LockError(JarError):
    """Raised when another JAR process holds the operation lock."""


class SafetyError(JarError):
    """Raised when an operation would touch a protected location."""


class RuleError(JarError):
    """Raised for invalid rule definitions."""
