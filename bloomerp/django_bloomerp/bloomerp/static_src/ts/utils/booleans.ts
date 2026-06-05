const TRUE_VALUES = new Set(["true", "1", "yes", "on"]);
const FALSE_VALUES = new Set(["false", "0", "no", "off"]);

export function parseBoolean(value: unknown, defaultValue = false): boolean {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    if (typeof value !== "string") return defaultValue;

    const normalizedValue = value.trim().toLowerCase();
    if (!normalizedValue) return defaultValue;
    if (TRUE_VALUES.has(normalizedValue)) return true;
    if (FALSE_VALUES.has(normalizedValue)) return false;

    return defaultValue;
}
