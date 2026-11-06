import { BaseWidget } from './BaseWidget';

/** Enhance a native select with local search and removable in-field choices. */
export default class ChoiceWidget extends BaseWidget {
    private select: HTMLSelectElement | null = null;
    private input: HTMLInputElement | null = null;
    private control: HTMLElement | null = null;
    private selected: HTMLElement | null = null;
    private results: HTMLElement | null = null;
    private lifecycle: AbortController | null = null;
    private required = false;
    private resetTimer: ReturnType<typeof setTimeout> | null = null;
    private active = -1;
    private matches: HTMLOptionElement[] = [];
    private static nextId = 0;

    /** Keep the select as the submission source and create an accessible search UI. */
    public initialize(): void {
        this.destroy();
        this.select = this.element?.querySelector('select') ?? null;
        if (!this.select) return;
        this.lifecycle = new AbortController();
        const options = { signal: this.lifecycle.signal };
        this.required = this.select.required;
        this.select.required = false;
        this.select.hidden = true;
        this.control = document.createElement('div');
        this.control.className = 'flex flex-wrap items-center gap-1 min-h-10 border border-gray-200 rounded-xl bg-white px-3 py-2 focus-within:ring-1 focus-within:ring-primary';
        this.selected = document.createElement('div');
        this.selected.className = 'contents';
        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.className = 'min-w-16 w-16 flex-1 border-0 bg-transparent p-0 text-sm focus:outline-none focus:ring-0';
        this.input.id = this.select.id;
        this.select.removeAttribute('id');
        for (const name of ['aria-label', 'aria-labelledby', 'aria-describedby', 'aria-invalid']) {
            const value = this.select.getAttribute(name);
            if (value) this.input.setAttribute(name, value);
        }
        this.input.autocomplete = 'off';
        this.input.setAttribute('role', 'combobox');
        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-required', String(this.required));
        this.results = document.createElement('ul');
        this.results.id = `choice-results-${++ChoiceWidget.nextId}`;
        this.results.className = 'absolute left-0 right-0 top-full mt-1 z-50 bg-white border border-gray-200 max-h-52 overflow-auto rounded-md shadow-lg list-none m-0 p-0 text-sm';
        this.results.setAttribute('role', 'listbox');
        this.input.setAttribute('aria-controls', this.results.id);
        this.control.append(this.selected, this.input);
        this.element.append(this.control, this.results);
        this.input.addEventListener('input', this.search, options);
        this.input.addEventListener('focus', this.search, options);
        this.input.addEventListener('keydown', this.keydown, options);
        this.element.addEventListener('focusout', this.blur, options);
        this.results.addEventListener('mousedown', this.keepFocus, options);
        this.select.addEventListener('change', this.refresh, options);
        this.select.form?.addEventListener('reset', this.reset, options);
        this.refresh();
        this.close();
    }

    /** Prevent result clicks from moving focus away before selection. */
    private keepFocus = (event: MouseEvent): void => { event.preventDefault(); };

    /** Close the menu when keyboard or pointer focus leaves the widget. */
    private blur = (event: FocusEvent): void => {
        if (!this.element.contains(event.relatedTarget as Node | null)) this.close();
    };

    /** Synchronize native form resets after the browser restores default selections. */
    private reset = (): void => {
        if (this.resetTimer) clearTimeout(this.resetTimer);
        this.resetTimer = setTimeout((): void => {
            this.resetTimer = null;
            if (this.input) this.input.value = '';
            this.refresh();
            this.close();
        }, 0);
    };

    /** Paint selected labels safely and keep validation on the focusable search field. */
    private refresh = (): void => {
        if (!this.select || !this.input || !this.selected) return;
        this.input.disabled = this.select.disabled;
        this.selected.replaceChildren();
        for (const option of Array.from(this.select.selectedOptions)) {
            if (!option.value) continue;
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-sm max-w-full';
            const label = document.createElement('span');
            label.className = 'truncate';
            label.textContent = option.label;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = '×';
            remove.setAttribute('aria-label', `${this.element.dataset.removeLabel ?? 'Remove'} ${option.label}`);
            remove.disabled = this.select.disabled || option.disabled || (option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled);
            /** Remove this choice while retaining every other selected option. */
            remove.onclick = (): void => {
                option.selected = false;
                if (!this.select.multiple) this.select.selectedIndex = -1;
                this.changed();
                this.input.focus();
            };
            chip.append(label, remove);
            this.selected.append(chip);
        }
        this.input.setCustomValidity(this.required && !Array.from(this.select.selectedOptions).some((option: HTMLOptionElement): boolean => Boolean(option.value))
            ? this.element.dataset.requiredLabel ?? 'Please select a choice.' : '');
        this.search();
    };

    /** Filter labels locally and exclude selected or disabled choices. */
    private search = (): void => {
        if (!this.input || !this.select || !this.results) return;
        const query = this.input.value.trim().toLocaleLowerCase();
        this.matches = Array.from(this.select.options).filter((option: HTMLOptionElement): boolean =>
            Boolean(option.value) && !option.selected && !option.disabled
            && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled)
            && option.label.toLocaleLowerCase().includes(query));
        this.active = -1;
        this.input.removeAttribute('aria-activedescendant');
        this.results.replaceChildren();
        this.matches.forEach((option: HTMLOptionElement, index: number): void => {
            const item = document.createElement('li');
            item.id = `${this.results.id}-${index}`;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', 'false');
            item.className = 'px-3 py-2 cursor-pointer hover:bg-gray-100';
            item.textContent = option.label;
            /** Commit the clicked option through the native select. */
            item.onclick = (): void => { this.choose(option); };
            this.results.append(item);
        });
        if (!this.matches.length) {
            const empty = document.createElement('li');
            empty.className = 'px-3 py-2 text-gray-500';
            empty.textContent = this.element.dataset.emptyLabel ?? 'No results';
            this.results.append(empty);
        }
        this.results.hidden = this.select.disabled || document.activeElement !== this.input;
        this.input.setAttribute('aria-expanded', String(!this.results.hidden));
    };

    /** Select an option and clear the query ready for another selection. */
    private choose(option: HTMLOptionElement): void {
        if (this.select.disabled) return;
        option.selected = true;
        this.input.value = '';
        this.changed();
        if (!this.select.multiple) this.close();
    }

    /** Notify native form listeners and the common widget event contract. */
    private changed(): void {
        this.select.dispatchEvent(new Event('change', { bubbles: true }));
        this.onChange();
    }

    /** Support arrow navigation, Enter selection, and Escape dismissal. */
    private keydown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') { event.preventDefault(); this.close(); return; }
        if (event.key === 'Enter' && !this.results.hidden) {
            event.preventDefault();
            const option = this.matches[this.active < 0 ? 0 : this.active];
            if (option) this.choose(option);
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        event.preventDefault();
        if (this.results.hidden) this.search();
        if (!this.matches.length) return;
        this.active = this.active < 0
            ? (event.key === 'ArrowDown' ? 0 : this.matches.length - 1)
            : (this.active + (event.key === 'ArrowDown' ? 1 : -1) + this.matches.length) % this.matches.length;
        Array.from(this.results.children).forEach((item: Element, index: number): void => {
            item.setAttribute('aria-selected', String(index === this.active));
            item.classList.toggle('bg-gray-100', index === this.active);
        });
        const item = this.results.children[this.active];
        this.input.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
    };

    /** Hide results without modifying the selected value. */
    private close(): void {
        if (this.results) this.results.hidden = true;
        this.input?.setAttribute('aria-expanded', 'false');
        this.input?.removeAttribute('aria-activedescendant');
    }

    /** Return the same scalar or list represented by native form submission. */
    public getValue(): string | string[] {
        if (!this.select) return '';
        return this.select.multiple ? Array.from(this.select.selectedOptions, (option: HTMLOptionElement): string => option.value) : this.select.value;
    }

    /** Restore valid choices for form history and programmatic updates. */
    public setValue(value: unknown, emitChange: boolean = true): void {
        if (!this.select) return;
        const values = (Array.isArray(value) ? value : [value]).map(String);
        this.select.selectedIndex = -1;
        for (const option of Array.from(this.select.options)) {
            option.selected = values.includes(option.value);
            if (option.selected && !this.select.multiple) break;
        }
        this.input.value = '';
        if (emitChange) this.changed();
        else this.refresh();
    }

    /** Rebuild around swapped select markup and updated choices. */
    public override onAfterSwap(): void { this.initialize(); }

    /** Release listeners and return the original select to its fallback state. */
    public override destroy(): void {
        if (this.resetTimer) clearTimeout(this.resetTimer);
        this.resetTimer = null;
        this.lifecycle?.abort();
        this.lifecycle = null;
        if (this.select) {
            this.select.hidden = false;
            this.select.required = this.required;
            if (this.input?.id) this.select.id = this.input.id;
        }
        this.control?.remove();
        this.results?.remove();
        this.select = null;
        super.destroy();
    }
}
