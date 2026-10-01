import BaseComponent, { initComponents } from './BaseComponent';

/** Edit composable key/value rows without submitting partially edited mappings. */
export default class MappingWidget extends BaseComponent {
    private lifecycle: AbortController | null = null;
    private nextIndex: number = 0;

    /** Attach delegated handlers after the registry has constructed this component. */
    public initialize(): void {
        if (!this.element) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.nextIndex = this.element.querySelectorAll('[data-mapping-row]').length;
        this.element.addEventListener('click', this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener('change', this.onChange, { signal: this.lifecycle.signal });
    }

    /** Keep intermediate row edits local until the user applies the whole mapping. */
    private onChange = (event: Event): void => {
        event.stopPropagation();
    };

    /** Add, remove or apply mapping rows using the server-rendered child widgets. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement | null;
        if (!this.element || !target) return;
        if (target.closest('[data-mapping-add]')) {
            const template = this.element.querySelector<HTMLTemplateElement>('[data-mapping-template]');
            const rows = this.element.querySelector<HTMLElement>('[data-mapping-rows]');
            if (!template || !rows) return;
            const copy = document.createElement('template');
            copy.innerHTML = template.innerHTML.split('__prefix__').join(String(this.nextIndex++));
            rows.appendChild(copy.content.cloneNode(true));
            initComponents(rows);
        } else if (target.closest('[data-mapping-remove]')) {
            target.closest('[data-mapping-row]')?.remove();
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
