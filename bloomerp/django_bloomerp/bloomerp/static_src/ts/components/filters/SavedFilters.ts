import { t } from '@/utils/i18n';
import { addTooltip } from '@/utils/tooltip';
import { FilterApi } from './api';
import type { Filter, SavedFilter } from './definition';
import { button, element } from './dom';

/** Saved identity survives condition edits and subsequent saves. */
export class SavedFilters {
    readonly element = element('div', 'border-b border-gray-200');
    readonly dropdown = element('div', 'relative inline-block text-left');
    private trigger = button(t('Select'), () => { void this.toggle(); }, 'btn btn-primary btn-sm');
    private menu = element('div', 'bloomerp-dropdown-menu fixed z-[150] w-56 max-h-72 overflow-y-auto rounded-xl border border-gray-200 bg-white py-1 shadow-lg');
    private name = element('input', 'h-9 min-w-0 flex-1 border-0 bg-transparent px-3 py-0 text-sm focus:ring-2 focus:ring-inset focus:ring-primary');
    private saveButton: HTMLButtonElement;
    private search = element('input', 'input w-full');
    private results = element('div');
    private records: SavedFilter[] = [];
    private onSearch = (): void => { this.renderResults(); };
    private filterId?: string;
    private destroyed = false;
    private busy = false;
    private onOutsideClick = (event: MouseEvent): void => {
        const target = event.target as Node;
        if (!this.dropdown.contains(target) && !this.menu.contains(target)) this.close(false);
    };
    private onMenuClick = (event: MouseEvent): void => { event.stopPropagation(); };
    private onParentClose = (): void => { this.close(false); };
    private position = (): void => {
        if (!this.trigger.isConnected || !this.trigger.getClientRects().length) { this.close(false); return; }
        const anchor = this.trigger.getBoundingClientRect();
        const padding = 8;
        this.menu.style.maxWidth = `${window.innerWidth - padding * 2}px`;
        this.menu.style.maxHeight = `${Math.min(288, window.innerHeight - padding * 2)}px`;
        const width = this.menu.offsetWidth;
        const height = this.menu.offsetHeight;
        const left = Math.max(padding, Math.min(anchor.right - width, window.innerWidth - width - padding));
        const below = anchor.bottom + padding;
        const top = below + height <= window.innerHeight - padding ? below : Math.max(padding, anchor.top - height - padding);
        this.menu.style.left = `${left}px`;
        this.menu.style.top = `${top}px`;
    };
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            this.close();
        }
    };

    constructor(
        private api: FilterApi,
        private getFilters: () => Filter[],
        private loadFilters: (filters: Filter[], isNew?: boolean) => void,
        private showError: (message: string) => void,
    ) {
        this.trigger.setAttribute('aria-haspopup', 'menu');
        this.trigger.setAttribute('aria-expanded', 'false');
        this.menu.setAttribute('role', 'menu');
        this.menu.setAttribute('aria-label', t('Saved filters'));
        this.menu.style.display = 'none';
        this.menu.style.position = 'fixed';
        this.menu.addEventListener('click', this.onMenuClick);
        this.search.type = 'search';
        this.search.placeholder = t('Search filters…');
        this.search.setAttribute('aria-label', t('Search saved filters'));
        this.search.addEventListener('input', this.onSearch);
        const searchRow = element('div', 'px-3 py-2');
        searchRow.append(this.search);
        const add = this.item(t('Add filter'), () => {
            this.filterId = undefined;
            this.name.value = '';
            this.showError('');
            this.loadFilters([], true);
            this.close(false);
            this.name.focus({ preventScroll: true });
        });
        const plus = element('i', 'fa-solid fa-plus mr-3');
        plus.setAttribute('aria-hidden', 'true');
        add.prepend(plus);
        const divider = element('div', 'border-t border-gray-200 my-1');
        divider.setAttribute('role', 'separator');
        this.menu.append(searchRow, add, divider, this.results);
        this.dropdown.append(this.trigger);
        this.name.type = 'text';
        this.name.maxLength = 255;
        this.name.placeholder = t('Filter name');
        this.name.setAttribute('aria-label', t('Filter name'));
        this.saveButton = button('', () => { void this.save(); }, 'inline-flex h-9 w-9 shrink-0 items-center justify-center border-0 border-l border-gray-200 bg-transparent text-xs hover:bg-base disabled:opacity-50');
        this.saveButton.title = t('Save filter');
        this.saveButton.setAttribute('aria-label', t('Save filter'));
        addTooltip(this.saveButton, { text: t('Save filter'), position: 'bottom' });
        const icon = element('i', 'fa-solid fa-floppy-disk');
        icon.setAttribute('aria-hidden', 'true');
        this.saveButton.append(icon);
        const row = element('div', 'flex items-stretch');
        row.append(this.name, this.saveButton);
        this.element.append(row);
    }

    get identity(): { filter_id?: string; filter_name?: string } {
        return this.filterId ? { filter_id: this.filterId, filter_name: this.name.value.trim() } : {};
    }

    setIdentity(id?: string, name = ''): void {
        this.filterId = id;
        this.name.value = name;
    }

    private item(label: string, action: () => void): HTMLButtonElement {
        const item = button(label, action, 'flex items-center px-4 py-2 text-sm w-full text-left text-gray-700 hover:bg-gray-100 hover:text-primary-800 transition-colors duration-150');
        item.setAttribute('role', 'menuitem');
        return item;
    }

    private status(message: string, error = false): void {
        const status = element('p', 'px-4 py-2 text-sm ' + (error ? 'text-danger-dark' : 'text-muted'), message);
        status.setAttribute('role', error ? 'alert' : 'status');
        this.results.replaceChildren(status);
        this.position();
    }

    private renderResults(): void {
        const query = this.search.value.trim().toLocaleLowerCase();
        const matches = this.records.filter(record => record.name.toLocaleLowerCase().includes(query));
        this.results.replaceChildren();
        if (!matches.length) {
            this.status(this.records.length ? t('No matching filters.') : t('No saved filters yet.'));
            return;
        }
        matches.forEach(record => this.results.append(this.item(record.name, () => {
            try {
                this.showError('');
                this.loadFilters(record.filters);
                this.filterId = record.id;
                this.name.value = record.name;
                this.close();
            } catch (error) { this.showError((error as Error).message); this.close(); }
        })));
        this.position();
    }

    private async toggle(): Promise<void> {
        if (this.trigger.getAttribute('aria-expanded') === 'true') { this.close(); return; }
        if (this.busy || this.destroyed) return;
        this.busy = true;
        this.saveButton.disabled = true;
        this.trigger.setAttribute('aria-expanded', 'true');
        document.body.append(this.menu);
        this.menu.style.display = 'block';
        this.search.value = '';
        this.search.disabled = true;
        this.status(t('Loading saved filters…'));
        document.addEventListener('click', this.onOutsideClick);
        document.addEventListener('keydown', this.onKeyDown, true);
        window.addEventListener('resize', this.position);
        window.addEventListener('scroll', this.position, true);
        window.addEventListener('dropdown-close', this.onParentClose);
        try {
            const records = await this.api.presets();
            if (this.destroyed || this.trigger.getAttribute('aria-expanded') !== 'true') return;
            this.records = records;
            this.search.disabled = false;
            this.renderResults();
            this.search.focus({ preventScroll: true });
        } catch (error) {
            if (!this.destroyed && this.trigger.getAttribute('aria-expanded') === 'true') this.status((error as Error).message, true);
        } finally {
            this.busy = false;
            if (!this.destroyed) this.saveButton.disabled = false;
        }
    }

    private close(focus = true): void {
        this.menu.style.display = 'none';
        this.menu.remove();
        this.trigger.setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', this.onOutsideClick);
        document.removeEventListener('keydown', this.onKeyDown, true);
        window.removeEventListener('resize', this.position);
        window.removeEventListener('scroll', this.position, true);
        window.removeEventListener('dropdown-close', this.onParentClose);
        if (focus && !this.destroyed) this.trigger.focus();
    }

    private async save(): Promise<void> {
        if (this.busy || this.destroyed) return;
        this.busy = true;
        this.close(false);
        this.showError('');
        this.saveButton.disabled = this.trigger.disabled = true;
        try {
            const name = this.name.value.trim();
            if (!name) throw new Error(t('A filter name is required.'));
            const record = await this.api.savePreset(name, this.getFilters(), this.filterId);
            if (!this.destroyed) this.filterId = record.id;
        } catch (error) { if (!this.destroyed) this.showError((error as Error).message); }
        finally {
            this.busy = false;
            if (!this.destroyed) this.saveButton.disabled = this.trigger.disabled = false;
        }
    }

    destroy(): void {
        this.destroyed = true;
        this.close(false);
        this.menu.removeEventListener('click', this.onMenuClick);
        this.search.removeEventListener('input', this.onSearch);
    }
}
