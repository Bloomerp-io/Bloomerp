import BaseComponent from '../BaseComponent';
import { t as _ } from '@/utils/i18n';
import { FilterApi } from '../filters/api';
import FilterContainer from '../filters/FilterContainer';
import { button, element } from '../filters/dom';
import { destroyWidgets, initializeWidget, readWidget } from '../filters/widget';
import { addTooltip } from '@/utils/tooltip';
import type { FieldGroup, Filter, LookupDefinition } from '../filters/definition';

type Action = { action: string; target_field: string | null; config: Record<string, unknown> };
type Behavior = { id: string; name: string; enabled: boolean; events: string[]; conditions: Filter[]; actions: Action[] };
type Config = { version: 1; behaviors: Behavior[] };
type ActionDefinition = { id: string; label: string; requires_target_field: boolean; targets: { name: string; label: string }[] };
type ConditionField = { field: string; label: string; lookups: LookupDefinition[] };

/** Reorder editors without destroying their unsaved controls or pending requests. */
function moveEditor<T extends { root: HTMLElement }>(editors: T[], editor: T, offset: number): void {
    const index = editors.indexOf(editor);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= editors.length) return;
    [editors[index], editors[next]] = [editors[next], editors[index]];
    editor.root.parentElement?.append(...editors.map(item => item.root));
}

/** Create a compact icon-only control with an accessible label. */
function iconButton(
    label: string, icon: string, action: () => void,
    classes: string = 'inline-flex h-10 w-10 shrink-0 items-center justify-center border-0 border-l border-gray-200 bg-transparent text-sm hover:bg-base focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary focus-visible:-outline-offset-2',
): HTMLButtonElement {
    const control = button('', action, classes);
    control.setAttribute('aria-label', label);
    control.title = label;
    addTooltip(control, { text: label, position: 'bottom' });
    const glyph = element('i', `fa-solid ${icon}`);
    glyph.setAttribute('aria-hidden', 'true');
    control.append(glyph);
    return control;
}

/** Restrict the reusable filter editor to backend-approved draft capabilities. */
class BehaviorFilterApi extends FilterApi {
    /** Keep condition discovery local while reusing the existing value-editor endpoint. */
    constructor(root: HTMLElement, private catalog: ConditionField[]) {
        super(root, { scope: 'model', id: root.dataset.contentTypeId ?? '' });
    }
    /** Return only top-level fields supported by the behavior evaluator. */
    override async fields(): Promise<FieldGroup[]> {
        return [{ name: 'Form fields', fields: this.catalog }];
    }
    /** Return the selected field's Python-evaluable operators. */
    override async lookups(path: string): Promise<LookupDefinition[]> {
        return this.catalog.find(field => field.field === path)?.lookups ?? [];
    }
}

/** A single action owns its selection, async fragment, and configuration widgets. */
class ActionEditor {
    readonly root = element('div', 'px-3 py-3');
    private toolbar = element('div', 'flex flex-wrap items-center gap-2');
    private action = element('select', 'select min-w-0 flex-1');
    private target = element('select', 'select min-w-0 flex-1');
    private body = element('div', 'mt-3');
    private revision = 0;
    private ready = false;
    private controller = new AbortController();
    private prefix = `behavior-${crypto.randomUUID()}`;

    /** Render action and target choices without assuming any action-specific fields. */
    constructor(
        private host: HTMLElement, private definitions: ActionDefinition[], initial: Action,
        remove: () => void, moveUp: () => void, moveDown: () => void,
    ) {
        this.action.setAttribute('aria-label', 'Action');
        this.target.setAttribute('aria-label', 'Target field');
        this.action.append(new Option('Select action', ''));
        definitions.forEach(definition => this.action.append(new Option(definition.label, definition.id)));
        if (initial.action && !definitions.some(definition => definition.id === initial.action)) {
            this.action.append(new Option(`Unavailable action: ${initial.action}`, initial.action));
        }
        this.action.value = initial.action;
        this.toolbar.append(
            this.action, this.target,
            iconButton(_('Move action up'), 'fa-arrow-up', moveUp, 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white text-sm hover:bg-base'),
            iconButton(_('Move action down'), 'fa-arrow-down', moveDown, 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white text-sm hover:bg-base'),
            iconButton(_('Remove action'), 'fa-trash', remove, 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white text-sm hover:bg-base'),
        );
        this.root.append(this.toolbar, this.body);
        this.action.addEventListener('change', (): void => this.selectAction(null, {}));
        this.target.addEventListener('change', (): void => { void this.load({}); });
        this.selectAction(initial.target_field, initial.config);
    }

    /** Rebuild eligible targets and discard configuration only after a selection change. */
    private selectAction(target: string | null, config: Record<string, unknown>): void {
        const definition = this.definitions.find(item => item.id === this.action.value);
        this.target.replaceChildren(new Option('Select target field', ''));
        definition?.targets.forEach(field => this.target.append(new Option(field.label, field.name)));
        this.target.hidden = !definition?.requires_target_field;
        if (target && !definition?.targets.some(field => field.name === target)) {
            this.target.append(new Option(`Unavailable field: ${target}`, target));
        }
        this.target.value = target ?? '';
        void this.load(config);
    }

    /** Fetch one Django fragment, ignoring stale responses after selections change. */
    private async load(config: Record<string, unknown>): Promise<void> {
        const revision = ++this.revision;
        this.ready = false;
        destroyWidgets(this.body);
        this.body.replaceChildren();
        const definition = this.definitions.find(item => item.id === this.action.value);
        this.body.classList.remove('text-muted');
        if (!definition || (definition.requires_target_field && !this.target.value)) {
            this.body.classList.add('text-muted');
            this.body.textContent = 'Select an action and its required target to configure it.';
            return;
        }
        this.body.textContent = 'Loading configuration…';
        try {
            const url = new URL(this.host.dataset.actionUrl!, location.href);
            const scope: Record<string, string> = JSON.parse(this.host.dataset.layoutContext ?? '{}');
            Object.entries(scope).forEach(([key, value]) => url.searchParams.set(key, String(value)));
            url.searchParams.set('listener_field_id', this.host.dataset.listenerId ?? '');
            url.searchParams.set('action_id', definition.id);
            url.searchParams.set('target_field', this.target.value);
            url.searchParams.set('prefix', this.prefix);
            url.searchParams.set('config', JSON.stringify(config));
            const response = await fetch(url, { signal: this.controller.signal, credentials: 'same-origin' });
            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                throw new Error(payload?.error ?? 'Could not load action configuration.');
            }
            const html = await response.text();
            if (revision !== this.revision) return;
            this.body.innerHTML = html;
            initializeWidget(this.body);
            this.ready = true;
        } catch (error) {
            if (revision === this.revision && (error as Error).name !== 'AbortError') {
                this.body.replaceChildren(element('p', 'text-danger-dark', (error as Error).message),
                    button('Retry', (): void => { void this.load(config); }));
            }
        }
    }

    /** Read the public widget values and decode fields declared as JSON by Django. */
    value(): Action {
        if (!this.ready) throw new Error('Complete every action and wait for its configuration to load.');
        const config: Record<string, unknown> = {};
        this.body.querySelectorAll<HTMLElement>('[data-config-key]').forEach(wrapper => {
            const value = readWidget(wrapper);
            config[wrapper.dataset.configKey!] = wrapper.dataset.configKind === 'json' && typeof value === 'string'
                ? (value.trim() ? JSON.parse(value) : null) : value;
        });
        return { action: this.action.value, target_field: this.target.hidden ? null : this.target.value, config };
    }

    /** Cancel requests and dispose embedded widgets before removing this action. */
    destroy(): void {
        ++this.revision;
        this.controller.abort();
        destroyWidgets(this.body);
        this.root.remove();
    }
}

/** Edit metadata, full filter groups, and an ordered action list for a behavior. */
class BehaviorEditor {
    readonly root = element('div');
    private card = element('div');
    private header = element('div', 'flex items-stretch border-b border-gray-200');
    private content = element('section');
    private divider = element('hr', 'm-0 border-gray-200');
    private name = element('input', 'h-10 min-w-0 flex-1 rounded-none rounded-tl-xl border-0 bg-transparent px-3 focus:ring-1 focus:ring-inset focus:ring-primary');
    private enabled = element('input');
    private event = element('select', 'h-10 w-44 shrink-0 rounded-none border-0 border-l border-gray-200 bg-transparent py-0 pl-3 pr-7 focus:ring-1 focus:ring-inset focus:ring-primary');
    private filterEditor: FilterContainer;
    private actions: ActionEditor[] = [];
    private conditionRoot = element('div', 'p-3');
    private actionRoot = element('div', 'divide-y divide-gray-200');
    private toggle: HTMLButtonElement | null = null;
    private collapsed = true;

    /** Restore an existing declaration and give new entries stable IDs. */
    constructor(private host: HTMLElement, private api: BehaviorFilterApi, private definitions: ActionDefinition[], private initial: Behavior, remove: () => void) {
        this.name.value = initial.name;
        this.name.placeholder = _('Behavior name');
        this.name.setAttribute('aria-label', _('Behavior name'));
        this.enabled.type = 'checkbox';
        this.enabled.checked = initial.enabled;
        const enabledLabel = element('label', 'flex h-10 shrink-0 items-center gap-2 border-l border-gray-200 px-3', 'Enabled');
        enabledLabel.prepend(this.enabled);
        this.event.setAttribute('aria-label', 'Run behavior');
        this.event.append(new Option('On change', 'change'), new Option('On initial load', 'initial'), new Option('Initial load and change', 'both'));
        this.event.value = initial.events.length === 2 ? 'both' : initial.events[0];
        Object.assign(this.conditionRoot.dataset, {
            scope: 'model', scopeId: host.dataset.contentTypeId ?? '',
            includeControls: 'false', allowEmpty: 'true',
            name: `conditions-${initial.id}`, initialFilters: JSON.stringify(initial.conditions),
        });
        this.filterEditor = new FilterContainer(this.conditionRoot, this.api);
        this.filterEditor.initialize();
        const removeControl = iconButton('Remove behavior', 'fa-trash', remove);
        removeControl.dataset.removeBehavior = '';
        this.toggle = iconButton('Show behavior', 'fa-chevron-down', (): void => this.setCollapsed(!this.collapsed));
        this.header.append(this.name, enabledLabel, this.event, removeControl, this.toggle);
        const conditionsPanel = element('section', 'min-w-0');
        const conditionsHeader = element('div', 'flex h-12 items-center border-b border-gray-200 px-3');
        conditionsHeader.append(element('h4', 'text-sm font-semibold', _('Conditions')));
        conditionsPanel.append(conditionsHeader, this.conditionRoot);
        const actionsPanel = element('section', 'min-w-0');
        const actionsHeader = element('div', 'flex h-12 items-center gap-2 border-b border-gray-200 px-3');
        actionsHeader.append(
            element('h4', 'text-sm font-semibold', _('Actions')),
            iconButton(_('Add action'), 'fa-plus', (): void => this.addAction(), 'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-white text-sm hover:bg-base ml-auto'),
        );
        actionsPanel.append(actionsHeader, this.actionRoot);
        const panels = element('div', 'divide-x divide-gray-200');
        panels.style.display = 'grid';
        panels.style.gridTemplateColumns = 'minmax(0, 1fr) minmax(0, 1fr)';
        panels.append(conditionsPanel, actionsPanel);
        this.content.append(panels);
        this.card.append(this.header, this.content);
        this.root.append(this.card, this.divider);
        this.setCollapsed(true);
        initial.actions.forEach(action => this.addAction(action));
    }

    /** Append an independently prefixed action form. */
    private addAction(initial: Action = { action: '', target_field: null, config: {} }): void {
        const editor = new ActionEditor(
            this.host, this.definitions, initial,
            (): void => {
                this.actions = this.actions.filter(item => item !== editor);
                editor.destroy();
            },
            (): void => moveEditor(this.actions, editor, -1),
            (): void => moveEditor(this.actions, editor, 1),
        );
        this.actions.push(editor);
        this.actionRoot.append(editor.root);
    }

    /** Add controls to the behavior-card toolbar. */
    addControls(...controls: HTMLElement[]): void {
        this.header.querySelector('[data-remove-behavior]')?.before(...controls);
    }

    /** Toggle whether the behavior's editable body is displayed. */
    private setCollapsed(collapsed: boolean): void {
        this.collapsed = collapsed;
        this.content.hidden = collapsed;
        this.root.dataset.collapsed = String(collapsed);
        const label = collapsed ? 'Show behavior' : 'Hide behavior';
        this.toggle?.setAttribute('aria-label', label);
        if (this.toggle) this.toggle.title = label;
        const glyph = this.toggle?.querySelector('i');
        if (glyph) glyph.className = `fa-solid ${collapsed ? 'fa-chevron-down' : 'fa-chevron-up'}`;
    }

    /** Hide the trailing divider for the final behavior in the list. */
    setDividerVisible(visible: boolean): void {
        this.divider.hidden = !visible;
    }

    /** Serialize complete controls into the Pydantic-compatible behavior shape. */
    value(): Behavior {
        if (!this.actions.length) throw new Error('Each behavior needs at least one action.');
        return {
            id: this.initial.id, name: this.name.value, enabled: this.enabled.checked,
            events: this.event.value === 'both' ? ['initial', 'change'] : [this.event.value],
            conditions: this.filterEditor.getFilters(),
            actions: this.actions.map(editor => editor.value()),
        };
    }

    /** Dispose condition and action widgets when the parent builder is removed. */
    destroy(): void {
        this.filterEditor.destroy();
        this.actions.forEach(editor => editor.destroy());
        this.root.remove();
    }
}

/** Own the complete versioned declaration while Django renders action fields. */
export default class BehaviorBuilder extends BaseComponent {
    private lifecycle = new AbortController();
    private api: BehaviorFilterApi | null = null;
    private editors: BehaviorEditor[] = [];
    private input: HTMLInputElement | null = null;
    private error: HTMLElement | null = null;
    private valid = false;

    /** Restore declarations and synchronize the hidden JSON before form submission. */
    initialize(): void {
        if (!this.element) return;
        this.input = this.element.querySelector('[data-behavior-input]');
        this.error = this.element.querySelector('[data-builder-error]');
        try {
            const parsed: unknown = JSON.parse(this.input?.value.trim() || 'null');
            const candidate = parsed ?? { version: 1, behaviors: [] };
            if (typeof candidate !== 'object' || Array.isArray(candidate)
                || !('version' in candidate) || candidate.version !== 1
                || !('behaviors' in candidate) || !Array.isArray(candidate.behaviors)) {
                throw new Error('Invalid behavior configuration: expected version 1 with a behaviors list.');
            }
            const config = candidate as Config;
            const definitions: ActionDefinition[] = JSON.parse(this.element.dataset.actions ?? '[]');
            this.api = new BehaviorFilterApi(this.element, JSON.parse(this.element.dataset.conditionFields ?? '[]'));
            config.behaviors.forEach(behavior => this.addBehavior(definitions, behavior));
            this.element.querySelector('[data-add-behavior]')?.addEventListener('click', (): void => {
                this.addBehavior(definitions, {
                    id: crypto.randomUUID(), name: '', enabled: true, events: ['change'], conditions: [],
                    actions: [{ action: '', target_field: null, config: {} }],
                });
            }, { signal: this.lifecycle.signal });
            this.element.querySelector('[data-clear-behaviors]')?.addEventListener('click', (): void => {
                this.clearBehaviors();
            }, { signal: this.lifecycle.signal });
            this.valid = true;
        } catch (error) { this.showError((error as Error).message); }
        this.element.closest('form')?.addEventListener('submit', (event: SubmitEvent): void => {
            try {
                if (!this.valid) throw new Error('The saved behavior configuration cannot be edited in this format.');
                const config: Config = { version: 1, behaviors: this.editors.map(editor => editor.value()) };
                if (this.input) this.input.value = JSON.stringify(config);
                this.showError('');
            } catch (error) {
                event.preventDefault();
                event.stopImmediatePropagation();
                this.showError((error as Error).message);
            }
        }, { capture: true, signal: this.lifecycle.signal });
    }

    /** Add a behavior without rebuilding existing unsaved action forms. */
    private addBehavior(definitions: ActionDefinition[], value: Behavior): void {
        if (!this.element || !this.api) return;
        const editor = new BehaviorEditor(this.element, this.api, definitions, value, (): void => {
            this.editors = this.editors.filter(item => item !== editor);
            editor.destroy();
            this.refreshBehaviorDividers();
        });
        editor.addControls(
            iconButton('Move behavior up', 'fa-arrow-up', (): void => this.moveBehavior(editor, -1)),
            iconButton('Move behavior down', 'fa-arrow-down', (): void => this.moveBehavior(editor, 1)),
        );
        this.editors.push(editor);
        this.element.querySelector('[data-behavior-list]')?.append(editor.root);
        this.refreshBehaviorDividers();
    }

    /** Remove every behavior editor while retaining a valid empty configuration. */
    private clearBehaviors(): void {
        this.editors.forEach(editor => editor.destroy());
        this.editors = [];
        this.element?.querySelector('[data-behavior-list]')?.replaceChildren();
    }

    /** Move a behavior and retain one visible divider between adjacent entries. */
    private moveBehavior(editor: BehaviorEditor, offset: number): void {
        moveEditor(this.editors, editor, offset);
        this.refreshBehaviorDividers();
    }

    /** Show a divider after every behavior except the last one. */
    private refreshBehaviorDividers(): void {
        this.editors.forEach((editor, index) => editor.setDividerVisible(index < this.editors.length - 1));
    }

    /** Display restoration or validation errors without changing the stored value. */
    private showError(message: string): void {
        if (this.error) this.error.textContent = message;
    }

    /** Abort asynchronous work and clean up all embedded form controls. */
    override destroy(): void {
        this.lifecycle.abort();
        this.editors.forEach(editor => editor.destroy());
        this.editors = [];
        this.api?.destroy();
        super.destroy();
    }
}
