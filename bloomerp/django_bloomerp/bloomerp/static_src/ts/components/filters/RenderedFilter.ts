import BaseComponent, { getComponent } from '../BaseComponent';
import { Modal } from '../Modal';
import FilterContainer from './FilterContainer';
import { button, element } from './dom';
import { t } from '@/utils/i18n';
import { parseInitialFilters, type Filter, type FilterScope } from './definition';

export type RenderedFilterData = {
    key: string;
    label: string;
    filters: Filter[];
    scope: FilterScope;
    savedFilterId?: string;
    defaultFilterId?: string;
};
export type RenderedFilterEventDetail = RenderedFilterData;

/** Requests changes to active filters; hosts own application and persistence. */
export default class RenderedFilter extends BaseComponent {
    static readonly removeEvent = 'bloomerp:rendered-filter-remove';
    static readonly defaultEvent = 'bloomerp:rendered-filter-default';
    static readonly editEvent = 'bloomerp:rendered-filter-edit';
    private filter?: RenderedFilterData;
    private label?: HTMLButtonElement;
    private menu?: HTMLElement;
    private modalRoot?: HTMLElement;
    private modal?: Modal;
    private editor?: FilterContainer;
    private previousOverflow = '';
    private initialized = false;
    private onLabelClick = (): void => this.openMenu();
    private onOutsideClick = (event: MouseEvent): void => {
        if (!this.element?.contains(event.target as Node) && !this.menu?.contains(event.target as Node)) this.closeMenu();
    };
    private onEscape = (event: KeyboardEvent): void => {
        if (event.key === 'Escape' && this.menu) { event.stopPropagation(); this.closeMenu(); this.label?.focus(); }
    };
    private onModalClosed = (): void => { this.destroyModal(); this.label?.focus(); };
    private onEditorApply = (event: Event): void => {
        event.stopPropagation();
        const { filters, filter_id, filter_name } = (event as CustomEvent<{
            filters: Filter[]; filter_id?: string; filter_name?: string;
        }>).detail;
        if (this.filter) {
            this.filter.savedFilterId = filter_id;
            this.filter.label = filter_name ?? '';
        }
        this.destroyModal();
        this.confirmEdit(filters);
    };
    private positionMenu = (): void => {
        if (!this.menu || !this.label) return;
        if (!this.label.isConnected || !this.label.getClientRects().length) { this.closeMenu(); return; }
        const anchor = this.label.getBoundingClientRect();
        const width = this.menu.offsetWidth, height = this.menu.offsetHeight;
        this.menu.style.left = `${Math.max(8, Math.min(anchor.left, innerWidth - width - 8))}px`;
        this.menu.style.top = `${anchor.bottom + height + 8 < innerHeight ? anchor.bottom + 8 : Math.max(8, anchor.top - height - 8)}px`;
    };

    initialize(): void {
        if (!this.element || this.initialized) return;
        const { key, label, filters, scope, scopeId, savedFilterId, defaultFilterId } = this.element.dataset;
        if (!key || !scopeId || (scope !== 'model' && scope !== 'workspace')) throw new Error('RenderedFilter requires a key and scope.');
        this.label = this.element.querySelector<HTMLButtonElement>('[data-rendered-filter-label]') ?? undefined;
        if (!this.label) throw new Error('RenderedFilter requires a label button.');
        this.label.addEventListener('click', this.onLabelClick);
        this.setFilter({ key, label: label ?? '', filters: parseInitialFilters(filters ?? '[]'), scope: { scope, id: scopeId }, savedFilterId, defaultFilterId });
        this.initialized = true;
    }

    public setFilter(filter: RenderedFilterData): void {
        this.filter = structuredClone(filter);
        if (this.label) {
            this.label.textContent = filter.label;
            this.label.title = filter.label;
            this.label.classList.toggle('badge-secondary', Boolean(filter.defaultFilterId));
            this.label.classList.toggle('badge-primary', !filter.defaultFilterId);
        }
    }

    public openMenu(): void {
        if (this.menu) { this.closeMenu(); return; }
        if (!this.label) return;
        this.menu = element('div', 'bloomerp-dropdown-menu fixed z-[150] w-40 rounded-xl border border-gray-200 bg-white py-1 shadow-lg');
        this.menu.setAttribute('role', 'menu');
        this.menu.setAttribute('aria-label', t('Filter actions'));
        this.menu.style.position = 'fixed';
        const item = (label: string, action: () => void): HTMLButtonElement => {
            const control = button(label, action, 'block w-full px-4 py-2 text-left text-sm hover:bg-gray-100');
            control.setAttribute('role', 'menuitem');
            return control;
        };
        const canManage = this.element?.closest<HTMLElement>('[data-rendered-filters]')?.dataset.canManageDefaults === 'true';
        if (!this.filter?.defaultFilterId || canManage) this.menu.append(item(t('Remove'), () => this.requestRemove()));
        this.menu.append(item(t('Edit'), () => this.openEditor()));
        if (canManage && !this.filter?.defaultFilterId) this.menu.append(item(t('Set default'), () => {
            this.closeMenu();
            this.emit(RenderedFilter.defaultEvent);
        }));
        this.menu.addEventListener('click', event => event.stopPropagation());
        document.body.append(this.menu);
        this.label.setAttribute('aria-expanded', 'true');
        this.positionMenu();
        document.addEventListener('click', this.onOutsideClick);
        document.addEventListener('keydown', this.onEscape, true);
        window.addEventListener('resize', this.positionMenu);
        window.addEventListener('scroll', this.positionMenu, true);
        this.menu.querySelector<HTMLButtonElement>('button')?.focus();
    }

    private closeMenu(): void {
        this.menu?.remove();
        this.menu = undefined;
        this.label?.setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', this.onOutsideClick);
        document.removeEventListener('keydown', this.onEscape, true);
        window.removeEventListener('resize', this.positionMenu);
        window.removeEventListener('scroll', this.positionMenu, true);
    }

    public openEditor(): void {
        this.closeMenu();
        if (!this.filter || this.modalRoot) return;
        const template = this.element?.closest('[data-rendered-filters]')?.querySelector<HTMLTemplateElement>('[data-rendered-filter-modal]');
        const root = template?.content.firstElementChild?.cloneNode(true) as HTMLElement | undefined;
        if (!root) return;
        const id = 'rendered-filter-' + crypto.randomUUID();
        [root, ...root.querySelectorAll<HTMLElement>('*')].forEach(node => {
            Array.from(node.attributes).forEach(attribute => {
                if (attribute.value.includes('rendered-filter-editor')) node.setAttribute(attribute.name, attribute.value.replace(/rendered-filter-editor/g, id));
            });
        });
        const editorRoot = root.querySelector<HTMLElement>('[bloomerp-component="unified-filter-container"]');
        if (!editorRoot) return;
        editorRoot.dataset.initialFilters = JSON.stringify(this.filter.filters);
        editorRoot.dataset.scope = this.filter.scope.scope;
        editorRoot.dataset.scopeId = this.filter.scope.id;
        this.previousOverflow = document.body.style.overflow;
        document.body.append(root);
        this.modalRoot = root;
        this.modal = getComponent(root) as Modal;
        this.editor = getComponent(editorRoot) as FilterContainer;
        this.editor.setSavedFilterIdentity(this.filter.savedFilterId, this.filter.savedFilterId ? this.filter.label : '');
        root.addEventListener('bloomerp:modal-closed', this.onModalClosed);
        root.addEventListener(FilterContainer.applyEvent, this.onEditorApply);
        this.modal?.open();
    }

    private destroyModal(): void {
        if (!this.modalRoot) return;
        this.modalRoot.removeEventListener('bloomerp:modal-closed', this.onModalClosed);
        this.modalRoot.removeEventListener(FilterContainer.applyEvent, this.onEditorApply);
        this.editor?.destroy();
        this.modal?.destroy();
        this.modalRoot.remove();
        document.body.style.overflow = this.previousOverflow;
        this.modalRoot = undefined;
        this.editor = undefined;
        this.modal = undefined;
    }

    public requestRemove(): void { this.closeMenu(); this.emit(RenderedFilter.removeEvent); }
    public confirmEdit(filters: Filter[]): void { this.emit(RenderedFilter.editEvent, filters); }

    private emit(event: string, filters = this.filter?.filters): void {
        if (!this.filter || !filters) return;
        const detail = structuredClone({ ...this.filter, filters });
        this.element?.dispatchEvent(new CustomEvent<RenderedFilterEventDetail>(event, { bubbles: true, detail }));
    }

    destroy(): void {
        this.closeMenu();
        this.destroyModal();
        this.label?.removeEventListener('click', this.onLabelClick);
        this.label = undefined;
        this.filter = undefined;
        this.initialized = false;
    }
}
