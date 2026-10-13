import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { visibleConversationReadMarker } from './conversationReadMarker.ts';

/** Model layout visibility without requiring a browser window. */
function visibleRects(): DOMRectList { return [{ width: 400, height: 600 }] as unknown as DOMRectList; }

/** Check open, hidden, background and newly refreshed conversation states. */
function readVisibility(): void {
    const dom = new JSDOM('<aside><section><div class="im-messages"><article data-message-id="first"></article></div></section></aside>');
    const conversation = dom.window.document.querySelector('section')!;
    conversation.getClientRects = visibleRects;
    assert.equal(visibleConversationReadMarker(conversation, 'visible'), 'first');
    assert.equal(visibleConversationReadMarker(conversation, 'hidden'), null);
    conversation.parentElement!.hidden = true;
    assert.equal(visibleConversationReadMarker(conversation, 'visible'), null);
    conversation.parentElement!.hidden = false;
    const incoming = dom.window.document.createElement('article');
    incoming.dataset.messageId = 'incoming';
    conversation.querySelector('.im-messages')!.append(incoming);
    assert.equal(visibleConversationReadMarker(conversation, 'visible'), 'incoming');
    conversation.remove();
    assert.equal(visibleConversationReadMarker(conversation, 'visible'), null);
    dom.window.close();
}

test('read acknowledgements follow visible rendered messages only', readVisibility);
