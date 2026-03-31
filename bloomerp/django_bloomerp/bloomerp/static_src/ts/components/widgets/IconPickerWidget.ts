import { BaseWidget } from "./BaseWidget";

export default class IconPickerWidget extends BaseWidget {
    private hiddenInput: HTMLInputElement | null = null;
    private toggleButton: HTMLButtonElement | null = null;
    private dropdown: HTMLElement | null = null;
    private searchInput: HTMLInputElement | null = null;
    private iconButtons: HTMLButtonElement[] = [];
    private noResults: HTMLElement | null = null;
    private preview: HTMLElement | null = null;
    private labelEl: HTMLElement | null = null;
    private clearButton: HTMLButtonElement | null = null;
    private disabled: boolean = false;
    private outsideClickHandler: (e: MouseEvent) => void;

    public initialize(): void {
        this.hiddenInput = this.element.querySelector('input[type="hidden"]');
        this.toggleButton = this.element.querySelector('[data-action="toggle"]') as HTMLButtonElement | null;
        this.dropdown = this.element.querySelector('.icon-picker-dropdown') as HTMLElement | null;
        this.searchInput = this.element.querySelector('[data-action="search"]') as HTMLInputElement | null;
        this.clearButton = this.element.querySelector('[data-action="clear"]') as HTMLButtonElement | null;
        this.preview = this.element.querySelector('[data-selected-preview]') as HTMLElement | null;
        this.labelEl = this.element.querySelector('[data-selected-label]') as HTMLElement | null;
        this.noResults = this.element.querySelector('[data-no-results]') as HTMLElement | null;
        this.iconButtons = Array.from(this.element.querySelectorAll('.icon-picker-item')) as HTMLButtonElement[];
        this.disabled = this.element.dataset.disabled === 'true' || !!this.toggleButton?.disabled;
        this.outsideClickHandler = this.onOutsideClick.bind(this);

        if (!this.hiddenInput || !this.toggleButton || !this.dropdown) {
            return;
        }

        this.toggleButton.addEventListener('click', () => this.toggleDropdown());
        this.iconButtons.forEach((btn) => {
            btn.addEventListener('click', () => this.onIconClick(btn));
        });
        if (this.searchInput) {
            this.searchInput.addEventListener('input', () => this.filterIcons());
        }
        if (this.clearButton) {
            this.clearButton.addEventListener('click', () => this.clearSelection());
        }

        document.addEventListener('click', this.outsideClickHandler);

        if (this.hiddenInput.value) {
            const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === this.hiddenInput?.value);
            if (selectedButton) {
                this.setSelection(selectedButton.dataset.value || '', selectedButton.dataset.label || '', false);
            } else {
                this.setSelection(this.hiddenInput.value, this.hiddenInput.value, false);
            }
        }
    }

    public destroy(): void {
        document.removeEventListener('click', this.outsideClickHandler);
    }

    private toggleDropdown(force?: boolean): void {
        if (this.disabled || !this.dropdown) return;
        const isHidden = this.dropdown.classList.contains('hidden');
        const shouldOpen = force !== undefined ? force : isHidden;
        if (shouldOpen) {
            this.dropdown.classList.remove('hidden');
            this.searchInput?.focus();
        } else {
            this.dropdown.classList.add('hidden');
        }
    }

    private onOutsideClick(e: MouseEvent): void {
        if (!this.element.contains(e.target as Node)) {
            this.toggleDropdown(false);
        }
    }

    private onIconClick(button: HTMLButtonElement): void {
        if (this.disabled) return;
        const value = button.dataset.value || '';
        const label = button.dataset.label || value;
        this.setSelection(value, label);
        this.toggleDropdown(false);
    }

    private clearSelection(): void {
        if (this.disabled) return;
        this.setSelection('', '');
        this.toggleDropdown(false);
    }

    private setSelection(value: string, label: string, emitChange: boolean = true): void {
        const previousValue = this.getValue();

        if (this.hiddenInput) {
            this.hiddenInput.value = value;
        }

        this.iconButtons.forEach((btn) => {
            btn.classList.remove('border-primary', 'bg-primary/10');
        });

        const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === value);
        if (selectedButton) {
            selectedButton.classList.add('border-primary', 'bg-primary/10');
        }

        if (this.preview) {
            if (value) {
                this.preview.innerHTML = `<i class="${value}"></i>`;
            } else {
                this.preview.innerHTML = '<span class="text-gray-400 text-xs">Icon</span>';
            }
        }

        if (this.labelEl) {
            this.labelEl.textContent = label || 'Select icon';
        }

        if (emitChange && previousValue !== this.getValue()) {
            this.onChange();
        }
    }

    private filterIcons(): void {
        if (!this.searchInput) return;
        const term = this.searchInput.value.trim().toLowerCase();
        let visibleCount = 0;

        this.iconButtons.forEach((btn) => {
            const label = (btn.dataset.label || '').toLowerCase();
            const value = (btn.dataset.value || '').toLowerCase();
            const match = term.length === 0 || label.includes(term) || value.includes(term);
            btn.classList.toggle('hidden', !match);
            if (match) visibleCount += 1;
        });

        if (this.noResults) {
            this.noResults.classList.toggle('hidden', visibleCount > 0);
        }
    }

    public getValue(): string {
        return this.hiddenInput?.value || '';
    }

    public setValue(value: unknown, emitChange: boolean = false): void {
        const normalizedValue = typeof value === "string" ? value : "";
        const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === normalizedValue);
        const label = selectedButton?.dataset.label || normalizedValue;
        this.setSelection(normalizedValue, label, emitChange);
    }
}
