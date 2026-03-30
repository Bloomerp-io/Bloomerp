const LOOKUP_LABELS: Record<string, string> = {
    exact: "is",
    equals: "is",
    icontains: "contains",
    contains: "contains",
    startswith: "starts with",
    endswith: "ends with",
    gte: "≥",
    lte: "≤",
    gt: ">",
    lt: "<",
    isnull: "is empty",
    in: "in",
    year: "year is",
    month: "month is",
    day: "day is",
    week: "week is",
};

function humanizeFieldPath(value: string): string {
    return value
        .split("__")
        .filter(Boolean)
        .map((part) => part.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()))
        .join(" → ");
}

function stringifyFilterValue(value: string | string[] | null): string {
    if (Array.isArray(value)) {
        return value.join(", ");
    }

    return String(value ?? "");
}

export function formatFilterLabel(fieldPath: string, operator: string | null, value: string | string[] | null): string {
    const fieldLabel = humanizeFieldPath(fieldPath);
    const rawValue = stringifyFilterValue(value);
    const normalizedOperator = String(operator || "").toLowerCase();
    const lookupLabel = LOOKUP_LABELS[normalizedOperator] || normalizedOperator || "is";

    if (normalizedOperator === "isnull") {
        const lowered = rawValue.toLowerCase();
        return lowered === "true" || lowered === "1" || lowered === "yes"
            ? `${fieldLabel} is empty`
            : `${fieldLabel} has value`;
    }

    return `${fieldLabel} ${lookupLabel} ${rawValue}`;
}

export function formatFilterTooltip(fieldPath: string, operator: string | null, value: string | string[] | null): string {
    return `${fieldPath}${operator ? `__${operator}` : ""} = ${stringifyFilterValue(value)}`;
}
