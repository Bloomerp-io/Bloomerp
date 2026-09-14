import { getComponent } from '../BaseComponent';
import FilterContainer from './FilterContainer';
import RenderedFilter, { type RenderedFilterData, type RenderedFilterEventDetail } from './RenderedFilter';
import { parseInitialFilters, type Filter } from './definition';
import { FilterApi } from './api';
import type { SavedFilter } from './definition';
import { t } from '@/utils/i18n';

export type AppliedFilterIdentity = { filter_id?: string; filter_name?: string };

/** Compare JSON values independently of object key order, preserving array order. */
function filterIdentity(filters: Filter[]): string {
    return JSON.stringify(filters, (_key, value) =>
        value && typeof value === 'object' && !Array.isArray(value)
            ? Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]]))
            : value,
    );
}

/** Shared label collection; its host supplies the authoritative query and refresh action. */
export class RenderedFilters {
    private entries: RenderedFilterData[] = [];
    private components: RenderedFilter[] = [];
    private serialized?: string;
    private defaults: SavedFilter[] = [];
    private api: FilterApi;
    private error = document.createElement('p');
    private busy = false;
    private onDefault = (event: Event): void => { void this.setDefault(event); };
    private onRemove = (event: Event): void => void this.change(event, true);
    private onEdit = (event: Event): void => void this.change(event, false);

    constructor(private root: HTMLElement, private update: (filters: Filter[]) => void) {
        this.api = new FilterApi(root, { scope: root.dataset.scope as 'model' | 'workspace', id: root.dataset.scopeId! });
        this.defaults = JSON.parse(root.dataset.defaultFilters || '[]');
        this.error.className = 'text-sm text-danger-dark empty:hidden';
        this.error.setAttribute('role', 'alert');
        root.append(this.error);
        root.addEventListener(RenderedFilter.defaultEvent, this.onDefault);
        root.addEventListener(RenderedFilter.removeEvent, this.onRemove);
        root.addEventListener(RenderedFilter.editEvent, this.onEdit);
    }

    public restore(json: string | null): void {
        try {
            this.setFilters(parseInitialFilters(json ?? '[]'));
        }
        catch { /* The host/backend reports invalid query filters; never rewrite them here. */ }
    }

    public setFilters(filters: Filter[], identity?: AppliedFilterIdentity): void {
        const scope = this.root.dataset.scope;
        if (scope !== 'model' && scope !== 'workspace') return;
        const context = { scope, id: this.root.dataset.scopeId! } as const;
        const defaultEntries = this.defaults.map(record => ({
            key: crypto.randomUUID(), label: record.name, filters: structuredClone(record.filters),
            scope: context, savedFilterId: record.id, defaultFilterId: record.id,
        }));
        const regularFilters = this.withoutDefaultFilters(filters);
        const collections = identity?.filter_id ? [regularFilters] : regularFilters.map(group => [group]);
        const regularEntries = collections.filter(groups => groups.length).map(groups => ({
            key: crypto.randomUUID(), filters: structuredClone(groups), scope: context,
            label: identity?.filter_name || this.describe(groups), savedFilterId: identity?.filter_id,
        }));
        const entries = [...defaultEntries, ...regularEntries];
        const serialized = filterIdentity(entries.flatMap(entry => entry.filters));
        if (serialized === this.serialized && !identity?.filter_id) return;
        this.serialized = serialized;
        this.entries = entries;
        this.render();
    }

    private withoutDefaultFilters(filters: Filter[]): Filter[] {
        const remaining = structuredClone(filters);
        this.defaults.forEach(record => {
            const size = record.filters.length;
            if (!size) return;
            const identity = filterIdentity(record.filters);
            const index = remaining.findIndex((_group, start) =>
                start + size <= remaining.length
                && filterIdentity(remaining.slice(start, start + size)) === identity,
            );
            if (index >= 0) remaining.splice(index, size);
        });
        return remaining;
    }

    private describe(groups: Filter[]): string {
        return groups.map(group => group.conditions.length ? group.conditions.map(condition => {
            const value = typeof condition.value === 'string' ? condition.value : JSON.stringify(condition.value);
            return `${condition.field_path.replace(/__/g, ' › ').replace(/_/g, ' ')} ${condition.lookup_id.replace(/_/g, ' ')} ${value ?? ''}`.trim();
        }).join(` ${group.connector} `) : group.connector === 'AND' ? t('All rows') : t('No rows'))
            .map(label => groups.length > 1 ? `(${label})` : label).join(` ${t('AND')} `);
    }

    private async change(event: Event, remove: boolean): Promise<void> {
        const detail = (event as CustomEvent<RenderedFilterEventDetail>).detail;
        const current = this.entries.find(entry => entry.key === detail?.key);
        if (!current || this.busy) return;
        event.stopPropagation();
        if (remove && current.defaultFilterId) {
            if (this.busy || this.root.dataset.canManageDefaults !== 'true') return;
            this.busy = true;
            try {
                await this.api.defaultFilter('remove', this.root.dataset.hostId!, [], current.defaultFilterId);
                this.defaults = this.defaults.filter(record => record.id !== current.defaultFilterId);
                this.error.textContent = '';
            } catch (error) { this.error.textContent = (error as Error).message; return; }
            finally { this.busy = false; }
        }
        this.entries = this.entries.flatMap(entry => entry !== current ? [entry] : remove || !detail.filters.length ? [] : [{
            ...entry, filters: structuredClone(detail.filters),
            savedFilterId: detail.savedFilterId,
            label: detail.savedFilterId ? detail.label : this.describe(detail.filters),
        }]);
        const filters = this.entries.flatMap(entry => entry.filters);
        this.serialized = filterIdentity(filters);
        this.render();
        this.update(filters);
    }

    private async setDefault(event: Event): Promise<void> {
        event.stopPropagation();
        const detail = (event as CustomEvent<RenderedFilterEventDetail>).detail;
        const entry = this.entries.find(entry => entry.key === detail.key);
        if (!entry || this.busy || this.root.dataset.canManageDefaults !== 'true') return;
        this.busy = true;
        try {
            const record = await this.api.defaultFilter('add', this.root.dataset.hostId!, entry.filters, entry.savedFilterId);
            entry.savedFilterId = record.id;
            entry.defaultFilterId = record.id;
            entry.label = record.name;
            this.defaults = [...this.defaults.filter(item => item.id !== record.id), record];
            this.error.textContent = '';
            this.render();
        } catch (error) { this.error.textContent = (error as Error).message; }
        finally { this.busy = false; }
    }

    private render(): void {
        this.components.forEach(component => component.destroy());
        this.components = [];
        const list = this.root.querySelector<HTMLElement>('[data-rendered-filter-list]');
        const template = this.root.querySelector<HTMLTemplateElement>('[data-rendered-filter-template]');
        if (!list || !template) return;
        list.replaceChildren();
        this.entries.forEach(entry => {
            const node = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
            Object.assign(node.dataset, { key: entry.key, label: entry.label, filters: JSON.stringify(entry.filters),
                scope: entry.scope.scope, scopeId: entry.scope.id });
            if (entry.defaultFilterId) node.dataset.defaultFilterId = entry.defaultFilterId;
            if (entry.savedFilterId) node.dataset.savedFilterId = entry.savedFilterId;
            list.append(node);
            const component = getComponent(node) as RenderedFilter;
            if (component) this.components.push(component);
        });
    }

    /** Keep the host's main editor aligned after a label is edited or removed. */
    public syncEditor(host: HTMLElement, filters: Filter[]): void {
        host.querySelectorAll<HTMLElement>('[data-filter-host-editor] [bloomerp-component="unified-filter-container"]').forEach(root => {
            if (root.dataset.scope !== this.root.dataset.scope || root.dataset.scopeId !== this.root.dataset.scopeId) return;
            (getComponent(root) as FilterContainer | null)?.setFilters(filters);
        });
    }

    destroy(): void {
        this.api.destroy();
        this.error.remove();
        this.root.removeEventListener(RenderedFilter.defaultEvent, this.onDefault);
        this.components.forEach(component => component.destroy());
        this.components = [];
        this.root.removeEventListener(RenderedFilter.removeEvent, this.onRemove);
        this.root.removeEventListener(RenderedFilter.editEvent, this.onEdit);
    }
}
