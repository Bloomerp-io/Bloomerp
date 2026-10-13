import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { updateAgentProgress, renderAgentProgress, type AgentProgressState } from './agentProgress.ts';

/** Create a fresh presentation state for an accepted request. */
function initialState(): AgentProgressState {
    return {sequence: 0, key: 'waiting', toolTitle: ''};
}

/** Describe a committed public event without exposing provider reasoning. */
function progressEvent(sequence: number, eventType: string, data: Record<string, unknown> = {}): Record<string, unknown> {
    return {sequence, event_type: eventType, payload: {data}};
}

/** Show tools, approvals and visible writing while ignoring private or unrelated events. */
function mapsObservableStages(): void {
    const initial = initialState();
    assert.equal(updateAgentProgress(initial, progressEvent(1, 'tool.started', {tool_title: 'Search Notion'})).key, 'tool-running');
    assert.equal(updateAgentProgress(initial, progressEvent(2, 'tool.outcome', {status: 'completed'})).key, 'tool-completed');
    assert.equal(updateAgentProgress(initial, progressEvent(3, 'tool.outcome', {status: 'waiting'})).key, 'approval');
    assert.equal(updateAgentProgress(initial, progressEvent(4, 'run.paused', {wait_kind: 'approval'})).key, 'approval');
    assert.equal(updateAgentProgress(initial, progressEvent(5, 'run.paused', {wait_kind: 'timer'})).key, 'paused');
    assert.equal(updateAgentProgress(initial, progressEvent(6, 'approval.decided')).key, 'waiting');
    assert.equal(updateAgentProgress(initial, progressEvent(7, 'text.delta')).key, 'writing');
    assert.equal(updateAgentProgress(initial, progressEvent(8, 'tool.outcome', {status: 'rejected'})).key, 'tool-rejected');
    assert.equal(updateAgentProgress(initial, progressEvent(9, 'tool.outcome', {status: 'unknown'})).key, 'tool-failed');
    assert.equal(updateAgentProgress(initial, progressEvent(10, 'checkpoint.created', {reasoning: 'private'})), initial);
    assert.equal(updateAgentProgress(initial, progressEvent(11, 'usage.updated')), initial);
}

/** Preserve the newest stage through duplicate delivery, replay and terminal cleanup. */
function keepsSequenceOrder(): void {
    const started = updateAgentProgress(initialState(), progressEvent(5, 'tool.started', {tool_title: 'Lookup'}));
    assert.equal(updateAgentProgress(started, progressEvent(4, 'text.delta')), started);
    assert.equal(updateAgentProgress(started, progressEvent(5, 'tool.started')), started);
    for (const terminal of ['run.completed', 'run.failed', 'run.cancelled']) {
        const finished = updateAgentProgress(started, progressEvent(8, terminal));
        assert.equal(finished.key, null);
        assert.equal(finished.toolTitle, '');
        assert.equal(updateAgentProgress(finished, progressEvent(6, 'tool.started')), finished);
    }
}

/** Restore a running tool from a snapshot and reach the same stage through live delivery. */
function restoresSnapshot(): void {
    const event = progressEvent(15, 'tool.started', {tool_title: 'Read page'});
    const restored = updateAgentProgress(initialState(), event);
    const live = updateAgentProgress(updateAgentProgress(initialState(), progressEvent(10, 'text.delta')), event);
    assert.deepEqual(restored, live);
    assert.equal(updateAgentProgress(restored, {event_type: 'tool.started'}), restored);
}

/** Render malicious tool names literally and omit tool arguments from the status region. */
function rendersSafeStatus(): void {
    const dom = new JSDOM('<p></p>');
    const target = dom.window.document.querySelector('p')!;
    const state = updateAgentProgress(initialState(), progressEvent(1, 'tool.started', {
        tool_title: '<img src=x onerror=bad()>', arguments: {token: 'hidden-secret'}, reasoning: 'hidden-reasoning',
    }));
    renderAgentProgress(target, state, 'Running tool');
    assert.equal(target.textContent, 'Running tool: <img src=x onerror=bad()>');
    assert.equal(target.children.length, 0);
    assert.equal(target.hidden, false);
    const observer = new dom.window.MutationObserver(ignoreMutationDelivery);
    observer.observe(target, {childList: true, attributes: true});
    renderAgentProgress(target, {...state, sequence: 2}, 'Running tool');
    assert.equal(observer.takeRecords().length, 0);
    observer.disconnect();
    renderAgentProgress(target, updateAgentProgress(state, progressEvent(2, 'run.completed')), '');
    assert.equal(target.hidden, true);
    assert.equal(target.textContent, '');
}

/** Leave mutation delivery unused because the test examines queued changes synchronously. */
function ignoreMutationDelivery(records: MutationRecord[], observer: MutationObserver): void {}

test('operational events map to factual progress', mapsObservableStages);
test('ordered replay cannot regress progress or revive completed status', keepsSequenceOrder);
test('snapshot and live progress agree', restoresSnapshot);
test('tool titles are literal and terminal events clear the status region', rendersSafeStatus);
