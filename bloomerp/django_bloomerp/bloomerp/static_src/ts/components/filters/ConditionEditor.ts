import { t } from '@/utils/i18n';
import { FilterApi } from './api';
import type { FilterCondition, FieldGroup, LookupDefinition } from './definition';
import { button, element } from './dom';
import { destroyWidgets, initializeWidget, readWidget } from './widget';

/** One condition owns its navigation and editor lifecycle. */
export class ConditionEditor {
    readonly element = element('div', 'filter-condition');
    private path = '';
    private lookup: LookupDefinition | null = null;
    private valueRoot: HTMLElement | null = null;
    private revision = 0;
    private ready = false;
    private error = element('p', 'filter-condition-error text-danger-dark text-xs');
    private navigation = element('div', 'filter-condition-navigation');

    constructor(private api: FilterApi, remove: () => void, private changed: () => void = () => {}) {
        this.element.dataset.filterCondition = '';
        const header = element('div', 'flex items-start');
        this.navigation.classList.add('flex-1', 'min-w-0');
        const removeButton = button('×', remove, 'filter-condition-remove');
        removeButton.setAttribute('aria-label', t('Remove condition'));
        removeButton.title = t('Remove condition');
        header.append(this.navigation, removeButton);
        this.error.setAttribute('role', 'alert');
        this.element.append(header, this.error);
    }

    async initialize(initial?: FilterCondition): Promise<void> {
        const revision = ++this.revision;
        this.ready = false;
        this.navigation.replaceChildren();
        this.clearValue();
        await this.run(async () => {
            const groups = await this.api.fields();
            if (revision !== this.revision) return;
            await this.fields(groups, '', revision, initial);
        });
    }

    private async run(action: () => Promise<void>): Promise<void> {
        this.error.textContent = '';
        try { await action(); }
        catch (error) {
            if ((error as Error).name !== 'AbortError') this.error.textContent = (error as Error).message;
        }
        finally { this.changed(); }
    }

    private clearValue(): void {
        if (this.valueRoot) { destroyWidgets(this.valueRoot); this.valueRoot.remove(); }
        this.valueRoot = null;
        this.lookup = null;
        this.ready = false;
    }

    private async fields(groups: FieldGroup[], parent: string, revision: number, initial?: FilterCondition): Promise<void> {
        const row = element('div', 'filter-path-level');
        const select = element('select', 'select filter-field-select w-full');
        select.setAttribute('aria-label', t('Field'));
        select.append(new Option(t('Select field'), ''));
        const fields = groups.flatMap(group => group.fields);
        groups.forEach(group => {
            const options = document.createElement('optgroup');
            options.label = group.name;
            group.fields.forEach(field => options.append(new Option(field.label, String(fields.indexOf(field)))));
            select.append(options);
        });
        row.append(select);
        this.navigation.append(row);
        const choose = async (index: number, restore?: FilterCondition): Promise<void> => {
            while (row.nextElementSibling) row.nextElementSibling.remove();
            while (select.nextElementSibling) select.nextElementSibling.remove();
            this.clearValue();
            const field = fields[index];
            if (!field) return;
            const resolve = async (segment: string, saved?: FilterCondition): Promise<void> => {
                row.querySelector('[data-comparison]')?.remove();
                while (row.nextElementSibling) row.nextElementSibling.remove();
                this.clearValue();
                const current = ++this.revision;
                this.path = parent ? `${parent}__${segment}` : segment;
                await this.lookups(row, this.path, current, saved);
            };
            if (field.field === '') {
                const input = element('input', 'input w-full');
                input.placeholder = field.label;
                input.setAttribute('aria-label', field.label);
                const next = button(t('Select key'), () => void this.run(async () => {
                    if (!input.value || input.value.includes('__')) throw new Error(t('Enter a single field key.'));
                    await resolve(input.value);
                }));
                row.append(input, next);
                if (restore) {
                    input.value = restore.field_path.slice(parent.length + 2).split('__')[0];
                    await resolve(input.value, restore);
                }
            } else await resolve(field.field, restore);
        };
        select.addEventListener('change', () => {
            ++this.revision;
            void this.run(() => choose(Number(select.value === '' ? -1 : select.value)));
        });
        if (initial && revision === this.revision) {
            const matching = fields.map((field, index) => ({ field, index, path: parent ? `${parent}__${field.field}` : field.field }))
                .filter(item => item.field.field === '' || initial.field_path === item.path || initial.field_path.startsWith(item.path + '__'))
                .sort((a, b) => b.path.length - a.path.length)[0];
            if (!matching) throw new Error(t('The saved filter field is unavailable.'));
            select.value = String(matching.index);
            await choose(matching.index, initial);
        }
    }

    private async lookups(row: HTMLElement, path: string, revision: number, initial?: FilterCondition): Promise<void> {
        const lookups = await this.api.lookups(path);
        if (revision !== this.revision) return;
        const select = element('select', 'select filter-field-select w-full');
        select.setAttribute('aria-label', t('Lookup'));
        select.dataset.lookupSelect = '';
        select.append(new Option(t('Select lookup'), ''));
        lookups.forEach(lookup => select.append(new Option(lookup.label, lookup.id)));
        const comparison = element('div', 'filter-comparison');
        comparison.dataset.comparison = '';
        select.className = 'select filter-lookup-select';
        comparison.append(select);
        row.append(comparison);
        const choose = async (lookup: LookupDefinition, restore?: FilterCondition): Promise<void> => {
            while (row.nextElementSibling) row.nextElementSibling.remove();
            this.clearValue();
            const current = ++this.revision;
            if (!lookup) return;
            if (lookup.nested) {
                const groups = await this.api.fields(path, lookup.id);
                if (current === this.revision) await this.fields(groups, path, current, restore);
            } else {
                const result = await this.api.editor(path, lookup.id, restore?.value);
                if (current !== this.revision) return;
                this.path = path;
                this.lookup = lookup;
                this.valueRoot = element('div', 'filter-value-editor flex-1 min-w-0');
                // Trusted same-origin Django widget HTML; labels above use textContent.
                this.valueRoot.innerHTML = result.widget;
                // Django emits id_value for each editor. Scope IDs to this condition.
                const prefix = `filter-${crypto.randomUUID()}-`;
                this.valueRoot.querySelectorAll<HTMLElement>('[id]').forEach(node => {
                    const oldId = node.id;
                    this.valueRoot!.querySelectorAll<HTMLLabelElement>('label').forEach(label => {
                        if (label.htmlFor === oldId) label.htmlFor = prefix + oldId;
                    });
                    node.id = prefix + oldId;
                });
                this.valueRoot.querySelectorAll<HTMLInputElement>('input[type="radio"]').forEach(input => {
                    if (!input.closest('[bloomerp-component]')) input.name = prefix + input.name;
                });
                comparison.append(this.valueRoot);
                initializeWidget(this.valueRoot, restore?.value);
                this.ready = true;
            }
        };
        select.addEventListener('change', () => void this.run(() => choose(lookups.find(item => item.id === select.value))));
        if (initial) {
            if (path === initial.field_path && !initial.lookup_id) return;
            const candidates = path === initial.field_path ? lookups.filter(item => item.id === initial.lookup_id) : lookups.filter(item => item.nested);
            if (candidates.length !== 1) throw new Error(t('The saved filter lookup could not be restored.'));
            select.value = candidates[0].id;
            await choose(candidates[0], initial);
        }
    }

    getCondition(): FilterCondition {
        if (!this.ready || !this.lookup || !this.valueRoot) throw new Error(t('Complete every filter condition before applying.'));
        return { field_path: this.path, lookup_id: this.lookup.id, value: readWidget(this.valueRoot) };
    }
    destroy(): void { ++this.revision; this.clearValue(); this.element.remove(); }
}
