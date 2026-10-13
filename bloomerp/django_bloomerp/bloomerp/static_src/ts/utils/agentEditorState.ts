import type { ArtifactChoice } from '../components/agent/ArtifactPicker';

export type AgentEditorState = {
    conversationId: string | null;
    draft: string;
    attachments: ArtifactChoice[];
    open: boolean;
    historyVisible: boolean;
};

/** Validate optional tab-local editor data before restoring server-owned conversation IDs. */
export function parseAgentEditorState(value: string | null): AgentEditorState | null {
    try {
        const state = JSON.parse(value ?? 'null');
        if (!state || (state.conversationId !== null && (typeof state.conversationId !== 'string'
            || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(state.conversationId)))
            || typeof state.draft !== 'string' || typeof state.open !== 'boolean'
            || typeof state.historyVisible !== 'boolean' || !Array.isArray(state.attachments)
            || state.attachments.length > 20 || !state.attachments.every(isArtifactChoice)) return null;
        return state as AgentEditorState;
    } catch { return null; }
}

/** Accept display metadata and signed tokens while leaving authorization to the server. */
function isArtifactChoice(value: unknown): value is ArtifactChoice {
    if (!value || typeof value !== 'object') return false;
    const choice = value as Record<string, unknown>;
    for (const key of ['token', 'key', 'title', 'summary', 'type', 'icon']) {
        if (typeof choice[key] !== 'string') return false;
    }
    return true;
}
