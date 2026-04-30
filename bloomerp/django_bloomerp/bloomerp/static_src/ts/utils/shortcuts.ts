export type ShortcutDefinition = {
    key: string;
    mod: boolean;
    shift: boolean;
    alt: boolean;
};

const MODIFIER_ALIASES: Record<string, keyof Omit<ShortcutDefinition, "key">> = {
    mod: "mod",
    cmd: "mod",
    command: "mod",
    meta: "mod",
    ctrl: "mod",
    control: "mod",
    shift: "shift",
    alt: "alt",
    option: "alt",
};

const KEY_ALIASES: Record<string, string> = {
    esc: "escape",
    return: "enter",
    spacebar: "space",
    " ": "space",
    up: "arrowup",
    down: "arrowdown",
    left: "arrowleft",
    right: "arrowright",
    plus: "+",
};

export function isMacPlatform(): boolean {
    if (typeof navigator === "undefined") return false;

    return (
        (navigator.platform && navigator.platform.toUpperCase().includes("MAC")) ||
        (navigator.userAgent && navigator.userAgent.includes("Mac"))
    );
}

export function parseShortcut(shortcut: string): ShortcutDefinition | null {
    const normalized = shortcut.trim().toLowerCase();
    if (!normalized) return null;

    const tokens = normalized
        .split("+")
        .map((token) => token.trim())
        .filter(Boolean);

    if (tokens.length === 0) return null;

    const definition: ShortcutDefinition = {
        key: "",
        mod: false,
        shift: false,
        alt: false,
    };

    for (const token of tokens) {
        const modifier = MODIFIER_ALIASES[token];
        if (modifier) {
            definition[modifier] = true;
            continue;
        }

        if (definition.key) {
            return null;
        }

        definition.key = normalizeShortcutKey(token);
    }

    return definition.key ? definition : null;
}

export function formatShortcutForDisplay(shortcut: ShortcutDefinition): string {
    if (isMacPlatform()) {
        return [
            shortcut.mod ? "⌘" : "",
            shortcut.shift ? "⇧" : "",
            shortcut.alt ? "⌥" : "",
            formatKeyLabel(shortcut.key),
        ].join("");
    }

    const parts: string[] = [];
    if (shortcut.mod) parts.push("Ctrl");
    if (shortcut.shift) parts.push("Shift");
    if (shortcut.alt) parts.push("Alt");
    parts.push(formatKeyLabel(shortcut.key));
    return parts.join("+");
}

export function formatShortcutForAria(shortcut: ShortcutDefinition): string {
    const parts: string[] = [];

    if (shortcut.mod) {
        parts.push(isMacPlatform() ? "Meta" : "Control");
    }
    if (shortcut.shift) {
        parts.push("Shift");
    }
    if (shortcut.alt) {
        parts.push("Alt");
    }

    parts.push(formatAriaKey(shortcut.key));
    return parts.join("+");
}

export function matchesShortcut(shortcut: ShortcutDefinition, event: KeyboardEvent): boolean {
    const key = normalizeKeyboardEventKey(event);
    const modPressed = isMacPlatform() ? event.metaKey : event.ctrlKey;
    const extraPlatformModifier = isMacPlatform() ? event.ctrlKey : event.metaKey;

    return (
        key === shortcut.key &&
        modPressed === shortcut.mod &&
        event.shiftKey === shortcut.shift &&
        event.altKey === shortcut.alt &&
        !extraPlatformModifier
    );
}

export function normalizeKeyboardEventKey(event: KeyboardEvent): string {
    return normalizeShortcutKey(event.key);
}

function normalizeShortcutKey(key: string): string {
    const trimmed = key.trim().toLowerCase();
    if (KEY_ALIASES[trimmed]) return KEY_ALIASES[trimmed];
    if (trimmed === "space") return "space";
    return trimmed;
}

function formatKeyLabel(key: string): string {
    switch (key) {
        case "arrowup":
            return "Up";
        case "arrowdown":
            return "Down";
        case "arrowleft":
            return "Left";
        case "arrowright":
            return "Right";
        case "escape":
            return "Esc";
        case "enter":
            return "Enter";
        case "space":
            return "Space";
        default:
            return key.length === 1 ? key.toUpperCase() : key.charAt(0).toUpperCase() + key.slice(1);
    }
}

function formatAriaKey(key: string): string {
    if (key === "space") return "Space";
    if (key.startsWith("arrow")) {
        return key.replace(/^arrow/, "Arrow").replace(/^Arrow([a-z])/, (_match, firstLetter: string) => `Arrow${firstLetter.toUpperCase()}`);
    }
    return key.length === 1 ? key.toUpperCase() : key.charAt(0).toUpperCase() + key.slice(1);
}
