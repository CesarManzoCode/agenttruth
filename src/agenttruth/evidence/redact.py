"""Redaction at the capture boundary (contract §12, ADR-0012).

Two mechanisms run on every text written through the evidence store:

1. Exact secret values loaded at startup from the environment (``ANTHROPIC_API_KEY`` and every
   ``AT_PH_*_KEY``), when at least 8 characters long.
2. Patterns: ``phx_``/``pha_``/``phs_`` PostHog tokens, ``sk-ant-`` Anthropic keys, ``Authorization``
   header values, ``authorization_token`` JSON values and ``token=`` URL parameters.

Each hit becomes ``[REDACTED:<kind>:<first 8 hex of sha256(secret)>]``, so equal secrets stay
correlatable without being recoverable.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["MIN_SECRET_LENGTH", "Redaction", "Redactor", "secret_env_names"]

MIN_SECRET_LENGTH = 8
_ENV_NAME = re.compile(r"^(ANTHROPIC_API_KEY|AT_PH_[A-Z0-9_]*_KEY)$")

# (kind, pattern); group "secret" is the part replaced, everything else is kept.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("authorization_token", re.compile(r'(?P<pre>"authorization_token"\s*:\s*")(?P<secret>[^"]+)(?=")')),
    (
        "authorization",
        re.compile(r'(?i)(?P<pre>\bauthorization"?\s*[:=]\s*"?(?:bearer\s+)?)(?P<secret>[^\s",}\']+)'),
    ),
    ("token_param", re.compile(r"(?P<pre>[?&]token=)(?P<secret>[^&\s\"'#]+)")),
    ("sk-ant", re.compile(r"(?P<pre>)(?P<secret>sk-ant-[A-Za-z0-9_\-]{8,})")),
    ("phx", re.compile(r"(?P<pre>)(?P<secret>\bphx_[A-Za-z0-9_\-]{8,})")),
    ("pha", re.compile(r"(?P<pre>)(?P<secret>\bpha_[A-Za-z0-9_\-]{8,})")),
    ("phs", re.compile(r"(?P<pre>)(?P<secret>\bphs_[A-Za-z0-9_\-]{8,})")),
)


def secret_env_names(env: Mapping[str, str]) -> list[str]:
    """Return the sorted names of environment variables whose values are secrets per §12."""
    return sorted(name for name in env if _ENV_NAME.match(name))


def _marker(kind: str, secret: str) -> str:
    return f"[REDACTED:{kind}:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:8]}]"


@dataclass(frozen=True)
class Redaction:
    """Result of redacting one text: the new text and how many replacements each kind made."""

    text: str
    hits: dict[str, int]

    @property
    def count(self) -> int:
        """Total number of replacements."""
        return sum(self.hits.values())


class Redactor:
    """Replaces secret values and secret-shaped tokens in text.

    Construct with explicit ``secrets`` (name → value) or via :meth:`from_environment`. Values shorter
    than :data:`MIN_SECRET_LENGTH` are ignored to avoid redacting ordinary words.
    """

    def __init__(self, secrets: Mapping[str, str]) -> None:
        literal = {name: value for name, value in secrets.items() if len(value) >= MIN_SECRET_LENGTH}
        # Longest first so that a secret containing another secret is replaced whole.
        self._literal = sorted(literal.items(), key=lambda item: (-len(item[1]), item[0]))

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Redactor:
        """Build a redactor from the secret variables present in ``env`` (e.g. ``os.environ``)."""
        return cls({name: env[name] for name in secret_env_names(env)})

    def redact(self, text: str) -> Redaction:
        """Return ``text`` with every secret replaced, plus per-kind hit counts. Pure; never raises."""
        hits: dict[str, int] = {}
        for name, value in self._literal:
            occurrences = text.count(value)
            if occurrences:
                text = text.replace(value, _marker(f"env:{name}", value))
                hits[f"env:{name}"] = hits.get(f"env:{name}", 0) + occurrences
        for kind, pattern in _PATTERNS:

            def replace(match: re.Match[str], kind: str = kind) -> str:
                secret = match["secret"]
                if secret.startswith("[REDACTED:"):
                    return match.group(0)
                hits[kind] = hits.get(kind, 0) + 1
                return match["pre"] + _marker(kind, secret)

            text = pattern.sub(replace, text)
        return Redaction(text=text, hits=hits)
