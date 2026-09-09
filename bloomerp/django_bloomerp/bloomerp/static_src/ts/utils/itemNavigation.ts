/** Shared field/tile/node navigation, independent of text editing shortcuts. */
export function getItemNavigationKey(event: KeyboardEvent): string | null {
    if (event.isComposing) return null;
    if (event.ctrlKey && event.altKey && !event.metaKey && event.key.startsWith('Arrow')) {
        return event.key;
    }
    // Keep the existing Mac Fn behavior as a compatibility alias.
    const fn = event.getModifierState('Fn');
    if (fn && event.key.startsWith('Arrow')) return event.key;
    if (fn || navigator.platform.toLowerCase().includes('mac')) {
        return ({ Home: 'ArrowLeft', End: 'ArrowRight', PageUp: 'ArrowUp', PageDown: 'ArrowDown' } as Record<string, string>)[event.key] || null;
    }
    return null;
}
