/** Return the newest rendered message only while the conversation is visible. */
export function visibleConversationReadMarker(element: HTMLElement, visibility: DocumentVisibilityState): string | null {
    if (visibility !== 'visible' || !element.isConnected || !element.getClientRects().length || element.closest('[hidden]')) return null;
    const messages = element.querySelectorAll<HTMLElement>('.im-messages [data-message-id]');
    return messages[messages.length - 1]?.dataset.messageId || null;
}
