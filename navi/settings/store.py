# navi/settings/store.py - typed settings on top of the registry: parse, validate, cache, persist, export/import
#
# ctx.settings.get("chance.kochi_reply") returns the override from the settings table or the registry default.
# Reads come from an in-memory cache (no DB hit per message); writes update the cache and the database together and
# record updated_by plus a setting_change event.

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from navi.db.repos.settings import delete_setting, load_overrides, set_setting
from navi.settings.registry import BY_KEY, CATEGORIES, SETTINGS, Setting, resolve

logger = logging.getLogger("navi.settings")

_TRUE = {"on", "true", "yes", "y", "1", "enable", "enabled"}
_FALSE = {"off", "false", "no", "n", "0", "disable", "disabled"}


class SettingError(ValueError):
    """A value was rejected by validation; str(exc) is safe to show to the admin."""


def _number(setting: Setting, value, cast):
    try:
        if isinstance(value, bool):
            raise ValueError
        num = cast(value)
    except (TypeError, ValueError):
        raise SettingError(f"{setting.label} needs a {'whole number' if cast is int else 'number'}.") from None
    if cast is int and isinstance(value, float) and value != num:
        raise SettingError(f"{setting.label} needs a whole number.")
    if setting.min is not None and num < setting.min or setting.max is not None and num > setting.max:
        raise SettingError(f"{setting.label} must be between {setting.min:g} and {setting.max:g}.")
    return num


def _snowflake(setting: Setting, value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise SettingError(f"{setting.label} needs a Discord ID.") from None
    if n <= 0:
        raise SettingError(f"{setting.label} needs a Discord ID.")
    return n


def validate(setting: Setting, value):
    """Check a Python value against the setting's kind and limits; return the normalised value."""
    kind = setting.kind
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise SettingError(f"{setting.label} is on or off.")
    if kind == "int":
        return _number(setting, value, int)
    if kind == "float":
        return float(_number(setting, value, float))
    if kind == "str":
        if not isinstance(value, str):
            raise SettingError(f"{setting.label} needs text.")
        if len(value) > 200:
            raise SettingError(f"{setting.label} is limited to 200 characters.")
        return value.strip()
    if kind == "choice":
        if value not in setting.choices:
            raise SettingError(f"{setting.label} must be one of: {', '.join(setting.choices)}.")
        return value
    if kind in ("channel", "role"):
        return None if value in (None, 0, "") else _snowflake(setting, value)
    if kind == "id_list":
        if not isinstance(value, (list, tuple, set)):
            raise SettingError(f"{setting.label} needs a list of IDs.")
        return sorted({_snowflake(setting, v) for v in value})
    raise SettingError(f"unsupported setting kind {kind!r}")


def parse(setting: Setting, text: str):
    """Turn what an admin typed (modal field or /admin set) into a validated value."""
    raw = text.strip()
    kind = setting.kind
    if kind == "bool":
        low = raw.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise SettingError(f"{setting.label} is on or off.")
    if kind in ("int", "float"):
        try:
            number = int(raw) if kind == "int" else float(raw)
        except ValueError:
            raise SettingError(f"{setting.label} needs a {'whole number' if kind == 'int' else 'number'}.") from None
        return validate(setting, number)
    if kind in ("channel", "role"):
        if raw.lower() in ("", "none", "off", "0", "clear"):
            return None
        m = re.fullmatch(r"<[#@&!]+(\d+)>|(\d+)", raw)
        if not m:
            raise SettingError(f"{setting.label} needs a mention or an ID (or 'none').")
        return validate(setting, int(m.group(1) or m.group(2)))
    if kind == "id_list":
        parts = [p for p in re.split(r"[,\s]+", raw) if p]
        return validate(setting, parts)
    return validate(setting, raw)


def format_value(setting: Setting, value) -> str:
    """Human-readable value for embeds and /admin get."""
    if setting.kind == "bool":
        return "on" if value else "off"
    if setting.kind == "channel":
        return f"<#{value}>" if value else "not set"
    if setting.kind == "role":
        return f"<@&{value}>" if value else "not set"
    if setting.kind == "id_list":
        return ", ".join(str(v) for v in value) if value else "none"
    if setting.kind == "float":
        return f"{value:g}"
    return str(value) if value not in (None, "") else "(empty)"


class Settings:
    """Cache over the settings table. Constructed empty (defaults only); bind() + load() attach the database."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}     # overrides only, by registry key
        self._db = None
        self._observers: list[Callable[[Setting, object], None]] = []

    # --- wiring
    def bind(self, db) -> None:
        self._db = db

    def load(self) -> None:
        """Reload every override from the database."""
        self._values = load_overrides(self._db) if self._db is not None else {}
        logger.info("Settings loaded (%d overrides)", len(self._values))

    def on_change(self, callback: Callable[[Setting, object], None]) -> None:
        """Call callback(setting, new_value) after every change (used to push AI settings into live objects)."""
        self._observers.append(callback)

    # --- reads
    def get(self, key: str):
        setting = resolve(key)
        return self._values.get(setting.key, setting.default)

    def is_default(self, key: str) -> bool:
        return resolve(key).key not in self._values

    def is_testing_guild(self, guild_id: int | None) -> bool:
        return guild_id is not None and guild_id in self.get("system.testing_guilds")

    def overrides(self) -> dict[str, object]:
        return dict(self._values)

    def category_counts(self) -> dict[str, tuple[int, int]]:
        """category -> (changed, total) over the settings shown in the panel."""
        out = {c: [0, 0] for c in CATEGORIES}
        for s in SETTINGS:
            if s.hidden:
                continue
            out[s.category][1] += 1
            if s.key in self._values:
                out[s.category][0] += 1
        return {c: (a, b) for c, (a, b) in out.items()}

    # --- writes
    def set(self, key: str, value, by: int | None = None):
        """Validate and store a value (a value equal to the default still records an explicit override)."""
        setting = resolve(key)
        value = validate(setting, value)
        if self._db is not None:
            set_setting(self._db, setting.key, value, by)
        self._values[setting.key] = value
        self._notify(setting, value)
        return value

    def set_text(self, key: str, text: str, by: int | None = None):
        return self.set(key, parse(resolve(key), text), by)

    def reset(self, key: str, by: int | None = None) -> bool:
        setting = resolve(key)
        existed = setting.key in self._values
        if self._db is not None:
            delete_setting(self._db, setting.key, by)
        self._values.pop(setting.key, None)
        self._notify(setting, setting.default)
        return existed

    def override(self, key: str, value) -> None:
        """Change the cached value only, with no validation or database write (tests)."""
        self._values[resolve(key).key] = value

    def _notify(self, setting: Setting, value) -> None:
        for cb in self._observers:
            try:
                cb(setting, value)
            except Exception:
                logger.exception("settings observer failed for %s", setting.key)

    # --- export / import
    def export_json(self) -> str:
        data = {"version": 1, "settings": {k: v for k, v in sorted(self._values.items())}}
        return json.dumps(data, indent=2, ensure_ascii=False)

    def import_json(self, text: str, by: int | None = None) -> tuple[list[str], list[str]]:
        """Apply an export. Returns (applied_keys, errors); valid entries are applied even if others fail."""
        try:
            data = json.loads(text)
            entries = data["settings"]
            if not isinstance(entries, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return [], ["That file is not a Navi settings export."]
        applied, errors = [], []
        for key, value in entries.items():
            setting = BY_KEY.get(key)
            if setting is None:
                errors.append(f"{key}: unknown setting")
                continue
            try:
                self.set(key, value, by)
                applied.append(key)
            except SettingError as exc:
                errors.append(f"{key}: {exc}")
        return applied, errors


FeatureFlags = Settings   # old name, kept for the test harness
