export function element<K extends keyof HTMLElementTagNameMap>(tag: K, classes = '', text?: string): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    node.className = classes;
    if (text !== undefined) node.textContent = text;
    return node;
}
export function button(label: string, action: () => void, classes = 'btn btn-secondary btn-sm'): HTMLButtonElement {
    const node = element('button', classes, label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
}
