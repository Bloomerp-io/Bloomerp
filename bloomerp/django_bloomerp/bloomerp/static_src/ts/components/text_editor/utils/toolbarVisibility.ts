export const TEXT_EDITOR_TOOLBAR_HIDDEN_COOKIE = "bloomerp-text-editor-toolbar-hidden";
export const TEXT_EDITOR_TOOLBAR_VISIBILITY_EVENT = "bloomerp:text-editor-toolbar-visibility-change";

const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

/** Return whether the shared toolbar should be collapsed, defaulting to collapsed. */
export function isToolbarHiddenFromCookie(cookie: string): boolean {
    for (const entry of cookie.split(";")) {
        const separatorIndex = entry.indexOf("=");

        if (separatorIndex === -1) {
            continue;
        }

        const name = entry.slice(0, separatorIndex).trim();
        if (name === TEXT_EDITOR_TOOLBAR_HIDDEN_COOKIE) {
            return entry.slice(separatorIndex + 1).trim() !== "false";
        }
    }

    return true;
}

export function createToolbarVisibilityCookie(hidden: boolean): string {
    return `${TEXT_EDITOR_TOOLBAR_HIDDEN_COOKIE}=${hidden ? "true" : "false"}; path=/; max-age=${COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
}
