import BaseComponent from '../BaseComponent';
import { t } from '@/utils/i18n';
import { FilterApi } from './api';
import { ConditionEditor } from './ConditionEditor';
import { SavedFilters } from './SavedFilters';
import { parseInitialFilters, type Filter, type FilterCondition } from './definition';
import { button, element } from './dom';
import { addTooltip } from '@/utils/tooltip';
import './editor.css';

type GroupEditor = { root: HTMLDivElement; content: HTMLElement; toggle: HTMLButtonElement; connector: HTMLSelectElement; rows: ConditionEditor[] };

export default class FilterContainer extends BaseComponent {
    static readonly applyEvent = 'bloomerp:filters-apply';
    private api: FilterApi;
    private groups: GroupEditor[] = [];
    private body = element('div', 'space-y-3 p-3 empty:hidden');
    private error = element('p', 'px-3 pb-3 text-sm text-danger-dark empty:hidden');
    private output = element('input');
    private initialized = false;
    private invalidInitialState = false;
    private presets?: SavedFilters;
    /** Allow embedded editors to supply scoped discovery while retaining the full group UI. */
    constructor(root?: HTMLElement, private suppliedApi?: FilterApi) {
        super(root);
    }

    private get singleGroup(): boolean { return this.element?.dataset.maxGroups === '1'; }
    private get includeControls(): boolean { return this.element?.dataset.includeControls !== 'false'; }
    private onEdit = (): void => { queueMicrotask(() => this.syncLiveValue()); };
    private onSubmit = (event: Event): void => {
        if (this.includeControls || this.output.disabled || event.target !== this.element?.closest('form')) return;
        try { this.output.value = JSON.stringify(this.getFilters()); }
        catch (error) { event.preventDefault(); this.output.value = ''; this.error.textContent = (error as Error).message; }
    };

    private syncLiveValue(): void {
        if (!this.initialized || this.includeControls) return;
        try { this.output.value = JSON.stringify(this.getFilters()); this.error.textContent = ''; }
        catch { this.output.value = ''; }
    }

    /** Restore groups and connect controls, optionally using an injected API. */
    initialize(): void {
        if (!this.element || this.initialized) return;
        this.initialized = true;
        const disabled = this.element.hasAttribute('disabled');
        const readonly = this.element.hasAttribute('readonly');
        this.element.inert = disabled || readonly;
        if (disabled || readonly) this.element.setAttribute('aria-disabled', 'true');
        this.output.disabled = disabled;
        const scope = this.getDataAttribute('scope');
        const id = this.getDataAttribute('scopeId');
        this.error.setAttribute('role', 'alert');
        this.output.type = 'hidden';
        this.output.name = this.getDataAttribute('name') ?? 'filter';
        this.output.dataset.widgetOutput = '';
        this.api = this.suppliedApi ?? new FilterApi(this.element, { scope: scope as 'model' | 'workspace', id });
        if (this.includeControls && this.element.dataset.presetsUrl) {
            this.presets = new SavedFilters(this.api, () => this.getFilters(), (filters, isNew) => {
                this.setFilters(filters);
                if (isNew && !this.groups.length) this.addGroup();
            }, message => { this.error.textContent = message; });
        }
        const controls = element('div', 'flex flex-wrap items-center gap-2 border-t border-gray-200 p-3');
        controls.dataset.filterControls = '';
        const primaryControls = element('div', 'ml-auto flex items-center gap-2');
        primaryControls.append(
            button(t('Apply'), () => this.apply(), 'btn btn-primary btn-sm'),
        );
        if (this.presets) primaryControls.append(this.presets.dropdown);
        controls.append(
            ...(!this.singleGroup ? [button(t('Add group'), () => this.addGroup())] : []),
            button(t('Clear'), () => { this.setFilters([]); }),
            primaryControls
        );
        const groupControls = element('div', 'px-3 pb-3');
        if (!this.singleGroup) groupControls.append(button(t('Add group'), () => this.addGroup()));
        this.element.replaceChildren(...(this.presets ? [this.presets.element] : []), this.body, this.error,
            ...(this.includeControls ? [controls] : !this.singleGroup ? [groupControls] : []), this.output);
        this.element.addEventListener('input', this.onEdit);
        this.element.addEventListener('change', this.onEdit);
        document.addEventListener('submit', this.onSubmit, true);
        try {
            if (!id || !['model', 'workspace'].includes(scope)) throw new Error(t('Filter scope is missing.'));
            const initialFilters = parseInitialFilters(this.getDataAttribute('initialFilters') ?? '[]');
            this.setFilters(initialFilters);
            if (this.groups.length === 0 && this.element.dataset.allowEmpty !== 'true') this.addGroup();
        } catch {
            this.invalidInitialState = true;
            this.error.textContent = t('Could not restore the initial filters.');
        }
    }

    private addGroup(initial?: Filter): void {
        const root = element('div', 'min-w-0 rounded-xl border border-gray-200');
        root.dataset.filterGroup = '';
        root.setAttribute('role', 'group');
        const toolbar = element('div', 'filter-group-toolbar flex items-stretch rounded-t-xl border-b border-gray-200');
        const actions = element('div', 'flex items-stretch');
        const connector = element('select', 'h-8 w-20 rounded-none rounded-tl-xl border-0 border-r border-gray-200 bg-transparent py-0 pl-3 pr-7 text-xs font-medium focus:ring-1 focus:ring-inset focus:ring-primary');
        connector.setAttribute('aria-label', t('Match conditions'));
        connector.append(new Option(t('AND'), 'AND'), new Option(t('OR'), 'OR'));
        connector.value = initial?.connector ?? 'AND';
        const rows = element('div');
        const toggle = this.iconButton(t('Collapse group'), 'fa-chevron-up', () => this.setGroupExpanded(group, rows.hidden));
        toggle.classList.remove('border-r');
        toggle.classList.add('border-l', 'rounded-tr-xl');
        toggle.setAttribute('aria-expanded', 'true');
        const group: GroupEditor = { root, content: rows, toggle, connector, rows: [] };
        const add = (condition?: FilterCondition): void => {
            const editor = new ConditionEditor(this.api, () => {
                editor.destroy();
                group.rows.splice(group.rows.indexOf(editor), 1);
                this.syncLiveValue();
            }, () => this.syncLiveValue());
            group.rows.push(editor);
            rows.append(editor.element);
            void editor.initialize(condition);
            this.syncLiveValue();
        };
        actions.append(this.iconButton(t('Add condition'), 'fa-plus', () => { this.setGroupExpanded(group, true); add(); }), this.iconButton(t('Remove group'), 'fa-trash', () => {
            if (this.singleGroup) { this.setFilters([]); return; }
            group.rows.forEach(row => row.destroy());
            this.groups.splice(this.groups.indexOf(group), 1);
            root.remove();
            this.updateGroupLabels();
            this.syncLiveValue();
        }));
        const spacer = element('span', 'flex-1');
        toolbar.append(connector, spacer, actions, toggle);
        root.append(toolbar, rows);
        this.groups.push(group);
        this.body.append(root);
        if (initial) initial.conditions.forEach(add); else add();
        this.updateGroupLabels();
        this.syncLiveValue();
    }

    private iconButton(label: string, icon: string, action: () => void): HTMLButtonElement {
        const control = button('', action, 'inline-flex h-8 w-8 shrink-0 items-center justify-center border-0 border-l border-gray-200 bg-transparent text-xs hover:bg-base focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary focus-visible:-outline-offset-2');
        control.setAttribute('aria-label', label);
        control.title = label;
        addTooltip(control, { text: label, position: 'bottom' });
        const glyph = element('i', `fa-solid ${icon}`);
        glyph.setAttribute('aria-hidden', 'true');
        control.append(glyph);
        return control;
    }

    private setGroupExpanded(group: GroupEditor, expanded: boolean): void {
        group.content.hidden = !expanded;
        group.root.dataset.collapsed = String(!expanded);
        group.toggle.setAttribute('aria-expanded', String(expanded));
        const label = expanded ? t('Collapse group') : t('Expand group');
        group.toggle.setAttribute('aria-label', label);
        group.toggle.title = label;
        addTooltip(group.toggle, { text: label, position: 'bottom' });
        group.toggle.querySelector('i')!.className = `fa-solid ${expanded ? 'fa-chevron-up' : 'fa-chevron-down'}`;
    }

    private updateGroupLabels(): void {
        this.body.querySelectorAll('[data-group-join]').forEach(label => label.remove());
        this.groups.forEach((group, index) => {
            group.root.setAttribute('aria-label', t('Condition group'));
            if (index > 0) {
                const join = element('div', 'text-xs font-medium px-3', t('AND'));
                join.dataset.groupJoin = '';
                group.root.before(join);
            }
        });
    }

    public getFilters(): Filter[] {
        if (this.invalidInitialState) throw new Error(t('Could not restore the initial filters. Clear them to start again.'));
        return this.groups.map(group => ({
            connector: group.connector.value as 'AND' | 'OR',
            conditions: group.rows.map(row => row.getCondition()),
        }));
    }

    public setFilters(filters: Filter[]): void {
        if (this.singleGroup && filters.length > 1) throw new Error(t('This editor accepts one condition group per rule.'));
        if (this.singleGroup && !filters.length) filters = [{ connector: 'AND', conditions: [] }];
        this.invalidInitialState = false;
        this.groups.forEach(group => group.rows.forEach(row => row.destroy()));
        this.groups = [];
        this.body.replaceChildren();
        this.error.textContent = '';
        filters.forEach(group => this.addGroup(group));
        this.output.value = JSON.stringify(filters);
        this.syncLiveValue();
    }

    private apply(): void {
        try {
            const filters = this.getFilters();
            this.output.value = JSON.stringify(filters);
            this.error.textContent = '';
            this.element?.dispatchEvent(new CustomEvent(FilterContainer.applyEvent, {
                bubbles: true, detail: { filters, scope: this.getDataAttribute('scope'), id: this.getDataAttribute('scopeId'), ...this.presets?.identity },
            }));
        } catch (error) { this.error.textContent = (error as Error).message; }
    }

    public setSavedFilterIdentity(id?: string, name = ''): void {
        this.presets?.setIdentity(id, name);
    }

    /** Release editor resources without disposing an API owned by the parent. */
    destroy(): void {
        this.initialized = false;
        this.element?.removeEventListener('input', this.onEdit);
        this.element?.removeEventListener('change', this.onEdit);
        document.removeEventListener('submit', this.onSubmit, true);
        if (!this.suppliedApi) this.api?.destroy();
        this.presets?.destroy();
        this.presets = undefined;
        this.groups.forEach(group => group.rows.forEach(row => row.destroy()));
        this.groups = [];
        this.initialized = false;
    }
}
