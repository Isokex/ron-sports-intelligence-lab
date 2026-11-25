"""Strict team identity resolution.

Source names drift between seasons: OpenFootball writes ``Aston Villa`` in
2019-20 and ``Aston Villa FC`` in 2024-25 for the same club. Resolving that is a
data decision, not a string-similarity problem, so it is recorded in a versioned
mapping file and applied by exact lookup.

Rules:

* Resolution is **exact alias lookup**. There is no fuzzy matching, no prefix
  matching and no case-insensitive fallback at runtime, because a wrong merge
  silently corrupts Elo history and shrinks the training sample.
* An unresolved name is returned as ``None`` and the caller rejects the record
  with a machine-readable reason. Nothing is invented.
* ``propose_key`` exists only for building a mapping for human review. It is
  never used to resolve a name during a build.
"""
from __future__ import annotations

import json
import re

CLUB_TOKENS = {"FC", "AFC", "CF", "SC", "AC"}


class IdentityError(RuntimeError):
    """The mapping file is unusable. Never downgraded to an empty mapping."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def propose_key(name: str) -> str:
    """Normalise a source name into a candidate grouping key, for review only.

    Strips club-type tokens, expands ``&``, casefolds and collapses whitespace.
    Two names sharing a key are *proposed* as the same club; a human confirms
    that by editing the mapping file, and only the mapping file resolves names.
    """
    if not isinstance(name, str):
        raise IdentityError("invalid_name", f"team name must be a string: {name!r}")
    tokens = [token for token in name.replace("&", "and").split() if token]
    kept = [token for token in tokens if token.upper() not in CLUB_TOKENS]
    return " ".join(kept).strip().casefold()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", propose_key(name)).strip("-")


class TeamResolver:
    """Exact-alias resolver backed by a versioned mapping document."""

    def __init__(self, mapping: dict):
        if not isinstance(mapping, dict):
            raise IdentityError("invalid_mapping", "mapping must be an object")
        version = mapping.get("version")
        if not isinstance(version, str) or not version:
            raise IdentityError("missing_version", "mapping needs a version")
        teams = mapping.get("teams")
        if not isinstance(teams, list) or not teams:
            raise IdentityError("missing_teams", "mapping needs a non-empty teams list")
        self.version = version
        self._index: dict[str, str] = {}
        self._display: dict[str, str] = {}
        for team in teams:
            if not isinstance(team, dict):
                raise IdentityError("invalid_team", "each team must be an object")
            team_id = team.get("team_id")
            if not isinstance(team_id, str) or not team_id:
                raise IdentityError("invalid_team", "each team needs a team_id")
            aliases = team.get("aliases")
            if not isinstance(aliases, list) or not aliases:
                raise IdentityError("missing_aliases", f"{team_id} has no aliases")
            self._display[team_id] = team.get("display_name") or team_id
            for alias in aliases:
                if not isinstance(alias, str) or not alias:
                    raise IdentityError("invalid_alias", f"{team_id} has an empty alias")
                existing = self._index.get(alias)
                if existing is not None and existing != team_id:
                    raise IdentityError(
                        "alias_collision",
                        f"{alias!r} maps to both {existing} and {team_id}",
                    )
                self._index[alias] = team_id

    @classmethod
    def load(cls, path: str) -> "TeamResolver":
        try:
            with open(path, encoding="utf-8") as fh:
                return cls(json.load(fh))
        except OSError as exc:
            raise IdentityError("mapping_unreadable", f"{path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise IdentityError("mapping_invalid_json", f"{path}: {exc}") from exc

    def resolve(self, name) -> str | None:
        """Exact lookup only. ``None`` means unresolved, never a guess."""
        if not isinstance(name, str):
            return None
        return self._index.get(name)

    def display_name(self, team_id: str) -> str:
        return self._display.get(team_id, team_id)

    def coverage(self, names) -> dict:
        """Report resolved and unresolved names with counts, for the audit."""
        resolved, unresolved = {}, {}
        for name in names:
            if self.resolve(name) is None:
                unresolved[name] = unresolved.get(name, 0) + 1
            else:
                resolved[name] = resolved.get(name, 0) + 1
        total = len(names)
        return {
            "mappingVersion": self.version,
            "namesSeen": total,
            "namesResolved": len(resolved),
            "namesUnresolved": len(unresolved),
            "recordsCoverage": (sum(resolved.values()) / total) if total else 0.0,
            "unresolvedNames": [{"name": k, "count": v}
                                for k, v in sorted(unresolved.items())],
        }
