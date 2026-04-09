import { BaseWidget } from "./BaseWidget";

export default class IconPickerWidget extends BaseWidget {
    private hiddenInput: HTMLInputElement | null = null;
    private toggleButton: HTMLButtonElement | null = null;
    private dropdown: HTMLElement | null = null;
    private searchInput: HTMLInputElement | null = null;
    private iconButtons: HTMLButtonElement[] = [];
    private colorButtons: HTMLButtonElement[] = [];
    private noResults: HTMLElement | null = null;
    private preview: HTMLElement | null = null;
    private labelEl: HTMLElement | null = null;
    private clearButton: HTMLButtonElement | null = null;
    private disabled: boolean = false;
    private selectedIconValue: string = "";
    private selectedLabel: string = "";
    private selectedColorValue: string = "";
    private outsideClickHandler: (e: MouseEvent) => void;
    private repositionHandler: () => void;

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
        this.colorButtons = Array.from(this.element.querySelectorAll('.icon-picker-color')) as HTMLButtonElement[];
        this.disabled = this.element.dataset.disabled === 'true' || !!this.toggleButton?.disabled;
        this.selectedColorValue = this.normalizeColor(this.element.dataset.defaultColor || this.colorButtons[0]?.dataset.colorValue || '');
        this.outsideClickHandler = this.onOutsideClick.bind(this);
        this.repositionHandler = this.positionDropdown.bind(this);

        if (!this.hiddenInput || !this.toggleButton || !this.dropdown) {
            return;
        }

        this.toggleButton.addEventListener('click', () => this.toggleDropdown());
        this.iconButtons.forEach((btn) => {
            btn.addEventListener('click', () => this.onIconClick(btn));
        });
        this.colorButtons.forEach((btn) => {
            btn.addEventListener('click', () => this.onColorClick(btn));
        });
        if (this.searchInput) {
            this.searchInput.addEventListener('input', () => this.filterIcons());
        }
        if (this.clearButton) {
            this.clearButton.addEventListener('click', () => this.clearSelection());
        }

        document.addEventListener('click', this.outsideClickHandler);
        window.addEventListener('resize', this.repositionHandler);
        window.addEventListener('scroll', this.repositionHandler, true);

        if (this.hiddenInput.value) {
            const parsedValue = this.parseSelectionValue(this.hiddenInput.value);
            const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === parsedValue.iconValue);
            if (selectedButton) {
                this.setSelection(
                    selectedButton.dataset.value || '',
                    selectedButton.dataset.label || '',
                    parsedValue.colorValue,
                    false,
                    !parsedValue.colorValue,
                );
            } else {
                this.setSelection(parsedValue.iconValue, parsedValue.iconValue, parsedValue.colorValue, false, !parsedValue.colorValue);
            }
        } else {
            this.updateColorSelectionStyles();
            this.renderPreview();
        }
    }

    public destroy(): void {
        document.removeEventListener('click', this.outsideClickHandler);
        window.removeEventListener('resize', this.repositionHandler);
        window.removeEventListener('scroll', this.repositionHandler, true);
    }

    private toggleDropdown(force?: boolean): void {
        if (this.disabled || !this.dropdown) return;
        const isHidden = this.dropdown.classList.contains('hidden');
        const shouldOpen = force !== undefined ? force : isHidden;
        if (shouldOpen) {
            this.dropdown.classList.remove('hidden');
            this.positionDropdown();
            this.searchInput?.focus();
        } else {
            this.dropdown.classList.add('hidden');
        }
    }

    private positionDropdown(): void {
        if (!this.dropdown || !this.toggleButton || this.dropdown.classList.contains('hidden')) return;

        const triggerRect = this.toggleButton.getBoundingClientRect();
        const dropdownWidth = this.dropdown.offsetWidth || 288;
        const dropdownHeight = this.dropdown.offsetHeight || 320;
        const viewportPadding = 12;

        let left = triggerRect.left;
        let top = triggerRect.bottom + 8;

        if (left + dropdownWidth > window.innerWidth - viewportPadding) {
            left = window.innerWidth - viewportPadding - dropdownWidth;
        }

        if (left < viewportPadding) {
            left = viewportPadding;
        }

        if (top + dropdownHeight > window.innerHeight - viewportPadding) {
            top = triggerRect.top - dropdownHeight - 8;
        }

        if (top < viewportPadding) {
            top = viewportPadding;
        }

        this.dropdown.style.left = `${left}px`;
        this.dropdown.style.top = `${top}px`;
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
        this.setSelection(value, label, this.selectedColorValue);
        this.toggleDropdown(false);
    }

    private onColorClick(button: HTMLButtonElement): void {
        if (this.disabled) return;
        const colorValue = button.dataset.colorValue || '';
        this.setSelection(this.selectedIconValue, this.selectedLabel, colorValue);
    }

    private clearSelection(): void {
        if (this.disabled) return;
        this.setSelection('', '', this.selectedColorValue || this.getDefaultColor());
        this.toggleDropdown(false);
    }

    private setSelection(
        iconValue: string,
        label: string,
        colorValue: string,
        emitChange: boolean = true,
        preserveExistingValue: boolean = false,
    ): void {
        const previousValue = this.getValue();
        const normalizedColor = this.normalizeColor(colorValue || this.selectedColorValue || this.getDefaultColor());
        const composedValue = preserveExistingValue ? previousValue : this.composeValue(iconValue, normalizedColor);

        this.selectedIconValue = iconValue;
        this.selectedLabel = label;
        this.selectedColorValue = normalizedColor;

        if (this.hiddenInput) {
            this.hiddenInput.value = composedValue;
        }

        this.iconButtons.forEach((btn) => {
            btn.classList.remove('border-primary', 'bg-primary/10');
        });

        const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === iconValue);
        if (selectedButton) {
            selectedButton.classList.add('border-primary', 'bg-primary/10');
        }

        this.updateColorSelectionStyles();
        this.renderPreview();

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
        const parsedValue = this.parseSelectionValue(normalizedValue);
        const selectedButton = this.iconButtons.find((btn) => btn.dataset.value === parsedValue.iconValue);
        const label = selectedButton?.dataset.label || parsedValue.iconValue;
        this.setSelection(parsedValue.iconValue, label, parsedValue.colorValue, emitChange, !parsedValue.colorValue);
    }

    private getDefaultColor(): string {
        return this.normalizeColor(this.element.dataset.defaultColor || this.colorButtons[0]?.dataset.colorValue || '');
    }

    private normalizeColor(value: string): string {
        const trimmedValue = value.trim().toUpperCase();
        if (!trimmedValue) return '';
        return trimmedValue.startsWith('#') ? trimmedValue : `#${trimmedValue}`;
    }

    private composeValue(iconValue: string, colorValue: string): string {
        const normalizedIcon = iconValue.trim();
        const normalizedColor = this.normalizeColor(colorValue);

        if (!normalizedIcon) {
            return '';
        }

        if (!normalizedColor) {
            return normalizedIcon;
        }

        return `${normalizedIcon} bg-[${normalizedColor}]/6 text-[${normalizedColor}]`;
    }

    private parseSelectionValue(value: string): { iconValue: string; colorValue: string } {
        const textMatch = value.match(/text-\[(#[0-9A-Fa-f]{6})\]/);
        const bgMatch = value.match(/bg-\[(#[0-9A-Fa-f]{6})\]\/(?:4|6)/);
        const colorValue = this.normalizeColor(textMatch?.[1] || bgMatch?.[1] || '');
        const iconValue = value
            .replace(/bg-\[(#[0-9A-Fa-f]{6})\]\/(?:4|6)/g, '')
            .replace(/text-\[(#[0-9A-Fa-f]{6})\]/g, '')
            .replace(/\s+/g, ' ')
            .trim();

        return { iconValue, colorValue };
    }

    private updateColorSelectionStyles(): void {
        this.colorButtons.forEach((btn) => {
            const isSelected = this.normalizeColor(btn.dataset.colorValue || '') === this.selectedColorValue;
            btn.classList.toggle('ring-2', isSelected);
            btn.classList.toggle('ring-gray-900', isSelected);
            btn.classList.toggle('ring-offset-2', isSelected);
            btn.classList.toggle('scale-[1.03]', isSelected);
        });
    }

    private renderPreview(): void {
        if (!this.preview) return;

        if (this.selectedIconValue) {
            const bgClass = this.selectedColorValue ? `bg-[${this.selectedColorValue}]/4` : 'bg-gray-100';
            const textClass = this.selectedColorValue ? `text-[${this.selectedColorValue}]` : 'text-gray-700';
            this.preview.innerHTML = `
                <span class="inline-flex h-9 w-9 items-center justify-center rounded-full ${bgClass}">
                    <i class="${this.selectedIconValue} ${textClass}"></i>
                </span>
            `;
            return;
        }

        this.preview.innerHTML = '<span class="inline-flex h-9 w-9 items-center justify-center rounded-full bg-gray-100 text-gray-400 text-xs">Icon</span>';
    }
}
