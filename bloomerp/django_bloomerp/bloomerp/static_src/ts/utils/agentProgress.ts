export type AgentProgressState = {sequence: number; key: string | null; toolTitle: string};

/** Map ordered operational events to translated status keys, excluding arguments and private reasoning. */
export function updateAgentProgress(current: AgentProgressState, event: Record<string, unknown>): AgentProgressState {
    if (typeof event.sequence !== 'number' || event.sequence <= current.sequence) return current;
    const payload = event.payload as {data?: {status?: unknown; tool_title?: unknown; wait_kind?: unknown}} | undefined;
    const data = payload?.data;
    let key: string | null;
    switch (event.event_type) {
        case 'tool.started': key = 'tool-running'; break;
        case 'tool.outcome':
            if (data?.status === 'waiting') key = 'approval';
            else if (data?.status === 'completed') key = 'tool-completed';
            else if (data?.status === 'rejected') key = 'tool-rejected';
            else key = 'tool-failed';
            break;
        case 'run.paused': key = data?.wait_kind === 'approval' ? 'approval' : 'paused'; break;
        case 'approval.decided': key = 'waiting'; break;
        case 'text.delta': key = 'writing'; break;
        case 'run.completed': case 'run.failed': case 'run.cancelled': key = null; break;
        default: return current;
    }
    const toolTitle = typeof data?.tool_title === 'string' && key?.startsWith('tool-')
        ? data.tool_title.slice(0, 511) : '';
    return {sequence: event.sequence, key, toolTitle};
}

/** Display trusted presentation labels and tool titles as literal text in the live status region. */
export function renderAgentProgress(target: HTMLElement, state: AgentProgressState, label: string): void {
    const hidden = state.key === null;
    const text = hidden ? '' : label + (state.toolTitle ? `: ${state.toolTitle}` : '');
    if (target.hidden !== hidden) target.hidden = hidden;
    // Token deltas advance the sequence frequently; announce a stage only when its label changes.
    if (target.textContent !== text) target.textContent = text;
}
