import assert from 'node:assert/strict';
import test from 'node:test';
import { parseAgentEditorState, type AgentEditorState } from './agentEditorState.ts';

/** Preserve drafts and completed conversation selection without requiring an active run. */
function restoresEditor(): void {
    const state: AgentEditorState = {
        conversationId: crypto.randomUUID(), draft: 'Unsent draft\nSecond line',
        attachments: [{token: 'signed', key: 'file', title: 'File', summary: '', type: 'file', icon: 'file'}],
        open: false, historyVisible: true,
    };
    assert.deepEqual(parseAgentEditorState(JSON.stringify(state)), state);
    assert.deepEqual(parseAgentEditorState(JSON.stringify({...state, conversationId: null})), {...state, conversationId: null});
}

/** Ignore corrupt or incompatible browser storage instead of breaking editor initialization. */
function rejectsInvalidState(): void {
    for (const value of [null, '{', '{}', JSON.stringify({conversationId: 'bad'})]) {
        assert.equal(parseAgentEditorState(value), null);
    }
    assert.equal(parseAgentEditorState(JSON.stringify({
        conversationId: null, draft: '', open: true, historyVisible: false, attachments: [{token: 2}],
    })), null);
}

test('editor state survives refresh independently of active execution', restoresEditor);
test('malformed editor storage is safely ignored', rejectsInvalidState);
