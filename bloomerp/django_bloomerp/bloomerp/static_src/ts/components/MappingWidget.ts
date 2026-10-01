import { getComponent, initComponents } from './BaseComponent';
import { BaseWidget, type BaseWidgetChangeDetail } from './widgets/BaseWidget';

type MappingValue = Array<[unknown, unknown]>;
type MappingControl = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

/** Edit composable key/value rows without submitting partially edited mappings. */
export default class MappingWidget extends BaseWidget {
    private lifecycle: AbortController | null = null;
    private nextIndex: number = 0;

    /** Attach delegated handlers after the registry has constructed this component. */
    public initialize(): void {
        if (!this.element) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.nextIndex = this.element.querySelectorAll('[data-mapping-row]').length;
        this.element.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener('change', this.handleInputChange, { signal: this.lifecycle.signal });
        this.element.addEventListener(BaseWidget.changeEventName, this.handleWidgetChange, { signal: this.lifecycle.signal });
    }

    /** Read ordered pairs, preserving incomplete or duplicate rows for state restoration. */
    public getValue(): MappingValue {
        const value: MappingValue = [];
        for (const row of this.element?.querySelectorAll<HTMLElement>('[data-mapping-rows] > [data-mapping-row]') ?? []) {
            value.push([this.readSide(row.querySelector('[data-mapping-key]')), this.readSide(row.querySelector('[data-mapping-value]'))]);
        }
        return value;
    }

    /** Restore pairs or a mapping object without submitting the containing form. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        if (!this.element) return;
        if (typeof value === 'string') value = JSON.parse(value);
        const pairs: MappingValue = [];
        if (Array.isArray(value)) {
            for (const pair of value) {
                if (!Array.isArray(pair) || pair.length !== 2) throw new TypeError('Expected mapping key/value pairs.');
                pairs.push([pair[0], pair[1]]);
            }
        } else if (value !== null && typeof value === 'object') {
            pairs.push(...Object.entries(value));
        } else if (value !== null && value !== undefined) {
            throw new TypeError('Expected a mapping object or key/value pairs.');
        }
        const rows = this.element.querySelector<HTMLElement>('[data-mapping-rows]');
        if (!rows) return;
        if (this.element.querySelector('[data-mapping-template]')) {
            for (const row of Array.from(rows.children)) this.removeRow(row as HTMLElement);
            for (const [key, mappedValue] of pairs) {
                const row = this.addRow();
                if (!row) continue;
                this.writeSide(row.querySelector('[data-mapping-key]'), key);
                this.writeSide(row.querySelector('[data-mapping-value]'), mappedValue);
            }
        } else {
            for (const row of rows.querySelectorAll<HTMLElement>('[data-mapping-row]')) {
                const key = this.readSide(row.querySelector('[data-mapping-key]'));
                let mappedValue: unknown = null;
                for (const pair of pairs) if (String(pair[0]) === String(key)) mappedValue = pair[1];
                this.writeSide(row.querySelector('[data-mapping-value]'), mappedValue);
            }
        }
        if (emitChange) this.onChange();
    }

    /** Find the custom widget that owns a row side's controls. */
    private childWidget(side: HTMLElement): BaseWidget | null {
        for (const node of side.querySelectorAll<HTMLElement>('[bloomerp-component]')) {
            const component = getComponent(node);
            if (component instanceof BaseWidget) return component;
        }
        return null;
    }

    /** Read native controls or delegate to a nested widget's value contract. */
    private readSide(side: HTMLElement | null): unknown {
        if (!side) return null;
        const widget = this.childWidget(side);
        if (widget) return widget.getValue();
        const controls = Array.from(side.querySelectorAll<MappingControl>('input[name], select[name], textarea[name]'));
        if (side.querySelector('[data-mapping-selection]')) {
            const selected: string[] = [];
            for (const control of controls) if (control instanceof HTMLInputElement && control.checked) selected.push(control.value);
            return selected;
        }
        const values: unknown[] = [];
        for (const control of controls) {
            if (control instanceof HTMLSelectElement && control.multiple) {
                const selected: string[] = [];
                for (const option of control.selectedOptions) selected.push(option.value);
                values.push(selected);
            } else if (control instanceof HTMLInputElement && control.type === 'radio') {
                if (control.checked) values.push(control.value);
            } else if (control instanceof HTMLInputElement && control.type === 'checkbox') {
                values.push(control.checked);
            } else values.push(control.value);
        }
        return values.length === 1 ? values[0] : values;
    }

    /** Restore native controls or delegate silently to a nested widget. */
    private writeSide(side: HTMLElement | null, value: unknown): void {
        if (!side) return;
        const widget = this.childWidget(side);
        if (widget) {
            widget.setValue(value, false);
            return;
        }
        const controls = Array.from(side.querySelectorAll<MappingControl>('input[name], select[name], textarea[name]'));
        const selection = side.querySelector<HTMLElement>('[data-mapping-selection]');
        const multiple = selection !== null || controls.some(this.isRadio);
        for (let index = 0; index < controls.length; index++) {
            const control = controls[index];
            const next = !multiple && controls.length > 1 && Array.isArray(value) ? value[index] : value;
            const selected = Array.isArray(next) ? next.map(String) : [String(next ?? '')];
            if (control instanceof HTMLSelectElement && control.multiple) {
                for (const option of control.options) option.selected = selected.includes(option.value);
            } else if (control instanceof HTMLInputElement && (control.type === 'radio' || selection)) {
                control.checked = selected.includes(control.value);
            } else if (control instanceof HTMLInputElement && control.type === 'checkbox') {
                control.checked = Boolean(next);
            } else control.value = String(next ?? '');
        }
        if (selection) this.updateSummary(selection);
    }

    /** Identify radio controls sharing a single logical value. */
    private isRadio(control: MappingControl): boolean {
        return control instanceof HTMLInputElement && control.type === 'radio';
    }

    /** Refresh the compact selected-values label after edits or restoration. */
    private updateSummary(selection: HTMLElement): void {
        const summary = selection.querySelector<HTMLElement>('[data-mapping-summary]');
        if (!summary) return;
        const labels: string[] = [];
        for (const input of selection.querySelectorAll<HTMLInputElement>('input:checked')) labels.push(input.dataset.choiceLabel ?? input.value);
        summary.textContent = labels.join(', ') || selection.dataset.emptyLabel || '';
    }

    /** Emit the composite widget value while keeping native form autosave behind Apply. */
    private handleInputChange = (event: Event): void => {
        event.stopPropagation();
        const selection = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-mapping-selection]');
        if (selection) this.updateSummary(selection);
        this.onChange();
    };

    /** Replace nested widget notifications with one mapping-level change notification. */
    private handleWidgetChange = (event: Event): void => {
        if ((event as CustomEvent<BaseWidgetChangeDetail>).detail.widget === this) return;
        event.stopPropagation();
        this.onChange();
    };

    /** Append and initialize a fresh row with unique child control identifiers. */
    private addRow(): HTMLElement | null {
        const template = this.element?.querySelector<HTMLTemplateElement>('[data-mapping-template]');
        const rows = this.element?.querySelector<HTMLElement>('[data-mapping-rows]');
        if (!template || !rows) return null;
        const copy = document.createElement('template');
        copy.innerHTML = template.innerHTML.split('__prefix__').join(String(this.nextIndex++));
        rows.appendChild(copy.content.cloneNode(true));
        const row = rows.lastElementChild as HTMLElement;
        initComponents(row);
        return row;
    }

    /** Release nested widget resources before removing a row. */
    private removeRow(row: HTMLElement): void {
        for (const node of row.querySelectorAll<HTMLElement>('[bloomerp-component]')) getComponent(node)?.destroy();
        row.remove();
    }

    /** Add, remove or apply mapping rows using the server-rendered child widgets. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement | null;
        if (!this.element || !target) return;
        if (target.closest('[data-mapping-add]')) {
            if (this.addRow()) this.onChange();
        } else if (target.closest('[data-mapping-remove]')) {
            const row = target.closest<HTMLElement>('[data-mapping-row]');
            if (row) {
                this.removeRow(row);
                this.onChange();
            }
        } else if (target.closest('[data-mapping-apply]')) {
            // Dispatch on the containing form so this widget's local handler does not intercept it.
            this.element.closest('form')?.dispatchEvent(new Event('change', { bubbles: true }));
        }
    };

    /** Release listeners owned by this editor. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
