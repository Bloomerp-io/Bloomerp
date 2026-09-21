import { getComponent } from '@/components/BaseComponent';
import type { Modal } from '@/components/Modal';
import { t } from './i18n';

export const MODAL_SIZE_CLASSES: Record<string, string> = {
    sm: 'max-w-sm', md: 'max-w-2xl', lg: 'max-w-4xl', xl: 'max-w-6xl', full: 'max-w-full',
};

interface ModalStackEntry {
    modal: Modal;
    opener: HTMLElement | null;
}

const openModals: ModalStackEntry[] = [];
let originalBodyOverflow = '';
let modalSequence = 0;

/** Build the shell once, moving supplied slot nodes without losing their state. */
export function buildModalShell(element: HTMLElement): void {
    if (element.querySelector(':scope > [data-modal-container]')) return;
    const content = element.querySelector(':scope > [data-modal-content]');
    const footerContent = element.querySelector(':scope > [data-modal-footer-content]');
    const container = document.createElement('div');
    container.id = `${element.id}-container`;
    container.dataset.modalContainer = '';
    container.className = 'bg-white rounded-xl shadow-xl max-h-full overflow-hidden w-full flex flex-col transform transition-all duration-200 ease-out scale-95 opacity-0';
    container.tabIndex = -1;
    container.setAttribute('role', 'dialog');
    container.setAttribute('aria-label', element.dataset.modalTitle || 'Modal');
    if (element.dataset.modalShowHeader !== 'false') {
        const header = document.createElement('div');
        header.className = `flex items-center justify-between p-3 border-b border-gray-200 ${element.dataset.modalHeaderClass || ''}`;
        const title = document.createElement('h3');
        title.id = `${element.id}-title`;
        title.className = 'text font-semibold text-primary-900';
        title.textContent = element.dataset.modalTitle || 'Modal';
        container.setAttribute('aria-labelledby', title.id);
        header.appendChild(title);
        if (element.dataset.modalClosable !== 'false') {
            const controls = document.createElement('div');
            controls.className = 'flex space-x-2';
            controls.append(
                buildModalButton(element.id, 'bloomerp-full-screen-modal', t('Toggle fullscreen'), 'fa-expand'),
                buildModalButton(element.id, 'bloomerp-close-modal', t('Close'), 'fa-times'),
            );
            header.appendChild(controls);
        }
        container.appendChild(header);
    }
    const body = document.createElement('div');
    body.id = `${element.id}-body`;
    body.dataset.modalBody = '';
    body.className = `min-h-0 overflow-y-auto ${element.dataset.modalBodyClass || ''}`;
    if (content) body.append(...Array.from(content.childNodes));
    container.appendChild(body);
    if (element.dataset.modalShowFooter === 'true') {
        const footer = document.createElement('div');
        footer.className = `flex items-center justify-end space-x-3 p-3 border-t border-gray-200 ${element.dataset.modalFooterClass || ''}`;
        if (footerContent) footer.append(...Array.from(footerContent.childNodes));
        container.appendChild(footer);
    }
    element.className = 'fixed inset-0 bg-black/50 z-[100] hidden items-start justify-center pt-12 p-4 transition-opacity duration-200 ease-out';
    element.replaceChildren(container);
}

/** Create an accessible shell control without inserting interpolated HTML. */
function buildModalButton(id: string, attribute: string, label: string, icon: string): HTMLButtonElement {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'hover:cursor-pointer';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.setAttribute(attribute, id);
    const glyph = document.createElement('i');
    glyph.className = `fas ${icon} text-primary-900 font-medium`;
    glyph.setAttribute('aria-hidden', 'true');
    button.appendChild(glyph);
    return button;
}

/** Return the last opened modal, independent of its declaration's DOM order. */
export function getTopModal(): Modal | null {
    return openModals[openModals.length - 1]?.modal || null;
}

/** Track an open modal and preserve the page's original scroll state. */
export function activateModal(modal: Modal, opener: HTMLElement | null): void {
    if (openModals.some((entry: ModalStackEntry): boolean => entry.modal === modal)) return;
    if (openModals.length === 0) originalBodyOverflow = document.body.style.overflow;
    openModals.push({ modal, opener });
    document.body.style.overflow = 'hidden';
    syncModalStack();
}

/** Release a closed modal and restore focus to its surviving opener or parent. */
export function deactivateModal(modal: Modal): void {
    const index = openModals.findIndex((entry: ModalStackEntry): boolean => entry.modal === modal);
    if (index < 0) return;
    const wasTop = getTopModal() === modal;
    const [entry] = openModals.splice(index, 1);
    if (openModals.length === 0) document.body.style.overflow = originalBodyOverflow;
    syncModalStack();
    if (!wasTop) return;
    const top = getTopModal();
    if (entry.opener?.isConnected && (!top || top.element.contains(entry.opener))) entry.opener.focus();
    else top?.focus();
}

/** Restrict interaction to the top dialog while keeping lower forms mounted. */
function syncModalStack(): void {
    openModals.forEach((entry: ModalStackEntry, index: number): void => {
        const active = index === openModals.length - 1;
        entry.modal.element.style.zIndex = String(100 + index * 2);
        entry.modal.element.inert = !active;
        entry.modal.element.setAttribute('aria-hidden', String(!active));
        entry.modal.element.querySelector('[data-modal-container]')?.setAttribute('aria-modal', String(active));
    });
}

/** Create an empty, disposable instance using a declaration's visual options. */
export function createModalInstance(declarationId: string, opener: HTMLElement): Modal {
    const declaration = document.getElementById(declarationId);
    if (!declaration) throw new Error(`Modal declaration not found: ${declarationId}`);
    const element = document.createElement('div');
    element.id = `${declarationId}-${++modalSequence}`;
    element.className = 'hidden';
    for (const attribute of Array.from(declaration.attributes)) {
        if (attribute.name.startsWith('data-modal-') || attribute.name === 'data-backdrop-click-close') {
            element.setAttribute(attribute.name, attribute.value);
        }
    }
    element.dataset.modalInstanceOf = declarationId;
    element.dataset.modalDisposable = 'true';
    element.setAttribute('bloomerp-component', 'modal');
    document.body.appendChild(element);
    const modal = getComponent(element) as Modal;
    modal.setOpener(opener);
    return modal;
}

/** Return the legacy shared modal with its declaration defaults restored. */
export default function getGeneralModal(): Modal {
    const modal = getModal('bloomerp-general-use-modal');
    modal.resetToDefaults();
    return modal;
}

/** Look up an existing modal through the component registry. */
export function getModal(id: string): Modal {
    return getComponent(document.getElementById(id)) as Modal;
}

/** Open an existing modal by its public declaration ID. */
export function openModal(modalId: string): void {
    getModal(modalId)?.open();
}

/** Close an existing modal by its public declaration ID. */
export function closeModal(modalId: string): void {
    getModal(modalId)?.close();
}
