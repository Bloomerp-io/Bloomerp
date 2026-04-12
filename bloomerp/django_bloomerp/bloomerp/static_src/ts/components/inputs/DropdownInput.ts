import BaseComponent from "../BaseComponent";

type DropdownOption = {
    element: HTMLButtonElement;
    label: string;
    value: string;
};

export default class DropdownInput extends BaseComponent {
    private inputElement: HTMLInputElement | null = null;
    private hiddenInputElement: HTMLInputElement | null = null;
    private optionsContainer: HTMLElement | null = null;
    private options: DropdownOption[] = [];
    private allowFreeValue = false;
    private selectedOption: DropdownOption | null = null;
    private activeOption: DropdownOption | null = null;
    private inputHandler: (() => void) | null = null;
    private focusHandler: (() => void) | null = null;
    private blurHandler: (() => void) | null = null;
    private keydownHandler: ((event: KeyboardEvent) => void) | null = null;
    private documentPointerDownHandler: ((event: PointerEvent) => void) | null = null;
    private optionHandlers: Array<{ option: DropdownOption; click: () => void; mouseDown: (event: MouseEvent) => void }> = [];
    private originalOptionsParent: HTMLElement | null = null;
    private originalNextSibling: ChildNode | null = null;
    private repositionHandler: (() => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.inputElement = this.element.querySelector<HTMLInputElement>('[data-dropdown-input-text]')
            ?? this.element.querySelector<HTMLInputElement>('input');
        this.optionsContainer = this.element.querySelector<HTMLElement>('[data-dropdown-options]');

        if (!this.inputElement || !this.optionsContainer) {
            console.warn('DropdownInput: Missing input or options container');
            return;
        }

        this.allowFreeValue = this.isTruthy(this.element.getAttribute('data-allow-free-value'));
        this.options = Array.from(this.element.querySelectorAll<HTMLButtonElement>('[data-dropdown-option]')).map((optionElement) => ({
            element: optionElement,
            label: optionElement.getAttribute('data-label') || optionElement.textContent?.trim() || '',
            value: optionElement.getAttribute('data-value') || optionElement.getAttribute('data-label') || optionElement.textContent?.trim() || '',
        }));

        this.createHiddenInput();
        this.bindEvents();
        this.syncInitialValue();
        this.filterOptions(this.inputElement.value);
        this.closeDropdown();
        this.renderOptions();
    }

    public destroy(): void {
        if (this.inputElement && this.inputHandler) {
            this.inputElement.removeEventListener('input', this.inputHandler);
        }

        if (this.inputElement && this.focusHandler) {
            this.inputElement.removeEventListener('focus', this.focusHandler);
        }

        if (this.inputElement && this.blurHandler) {
            this.inputElement.removeEventListener('blur', this.blurHandler);
        }

        if (this.inputElement && this.keydownHandler) {
            this.inputElement.removeEventListener('keydown', this.keydownHandler);
        }

        if (this.documentPointerDownHandler) {
            document.removeEventListener('pointerdown', this.documentPointerDownHandler);
        }

        // restore portaled options and remove any reposition handlers
        try {
            this.restoreOptionsContainer();
        } catch (e) {
            // ignore
        }

        this.optionHandlers.forEach(({ option, click, mouseDown }) => {
            option.element.removeEventListener('click', click);
            option.element.removeEventListener('mousedown', mouseDown);
        });

        this.optionHandlers = [];
        this.activeOption = null;
        this.selectedOption = null;
        this.options = [];
        this.optionsContainer = null;
        this.hiddenInputElement = null;
        this.inputElement = null;
        this.inputHandler = null;
        this.focusHandler = null;
        this.blurHandler = null;
        this.keydownHandler = null;
        this.documentPointerDownHandler = null;
    }

    private createHiddenInput(): void {
        if (!this.inputElement) return;

        const inputName = this.inputElement.getAttribute('name')?.trim() || '';
        if (!inputName) return;

        const hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.name = inputName;
        hiddenInput.value = this.inputElement.value;
        hiddenInput.setAttribute('data-dropdown-hidden-input', 'true');

        const formId = this.inputElement.getAttribute('form');
        if (formId) {
            hiddenInput.setAttribute('form', formId);
        }

        this.inputElement.removeAttribute('name');
        this.inputElement.insertAdjacentElement('afterend', hiddenInput);
        this.hiddenInputElement = hiddenInput;
    }

    private bindEvents(): void {
        if (!this.inputElement) return;

        this.inputHandler = () => {
            if (!this.inputElement) return;

            this.filterOptions(this.inputElement.value);
            this.syncTypedValue();
            this.openDropdown();
            this.renderOptions();
        };

        this.focusHandler = () => {
            if (!this.inputElement) return;
            this.filterOptions(this.inputElement.value);
            this.openDropdown();
            this.renderOptions();
        };

        this.blurHandler = () => {
            window.setTimeout(() => {
                if (!this.element?.contains(document.activeElement)) {
                    this.commitPendingValue();
                    this.closeDropdown();
                    this.renderOptions();
                }
            }, 0);
        };

        this.keydownHandler = (event: KeyboardEvent) => this.handleKeydown(event);
        this.documentPointerDownHandler = (event: PointerEvent) => {
            const target = event.target;
            if (!(target instanceof Node)) return;
            if (this.element?.contains(target)) return;

            this.commitPendingValue();
            this.closeDropdown();
            this.renderOptions();
        };

        this.inputElement.addEventListener('input', this.inputHandler);
        this.inputElement.addEventListener('focus', this.focusHandler);
        this.inputElement.addEventListener('blur', this.blurHandler);
        this.inputElement.addEventListener('keydown', this.keydownHandler);
        document.addEventListener('pointerdown', this.documentPointerDownHandler);

        this.options.forEach((option) => {
            const click = () => {
                this.selectOption(option);
            };
            const mouseDown = (event: MouseEvent) => {
                event.preventDefault();
            };

            option.element.addEventListener('click', click);
            option.element.addEventListener('mousedown', mouseDown);
            this.optionHandlers.push({ option, click, mouseDown });
        });
    }

    private syncInitialValue(): void {
        if (!this.inputElement) return;

        const initialValue = this.inputElement.value.trim();
        if (!initialValue) {
            this.updateHiddenValue('');
            return;
        }

        const matchingOption = this.findExactMatch(initialValue);
        if (matchingOption) {
            this.selectOption(matchingOption, false);
            return;
        }

        if (this.allowFreeValue) {
            this.updateHiddenValue(initialValue);
            return;
        }

        this.inputElement.value = '';
        this.updateHiddenValue('');
    }

    private syncTypedValue(): void {
        if (!this.inputElement) return;

        const currentValue = this.inputElement.value.trim();
        const exactMatch = this.findExactMatch(currentValue);

        if (exactMatch) {
            this.selectedOption = exactMatch;
            this.activeOption = exactMatch;
            this.updateHiddenValue(exactMatch.value);
            return;
        }

        this.selectedOption = null;

        if (this.allowFreeValue) {
            this.activeOption = null;
            this.updateHiddenValue(currentValue);
            return;
        }

        this.activeOption = this.getVisibleOptions()[0] || null;
        this.updateHiddenValue('');
    }

    private handleKeydown(event: KeyboardEvent): void {
        const visibleOptions = this.getVisibleOptions();

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.openDropdown();
            this.moveActiveOption(1, visibleOptions);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.openDropdown();
            this.moveActiveOption(-1, visibleOptions);
            return;
        }

        if (event.key === 'Enter') {
            if (this.activeOption) {
                event.preventDefault();
                this.selectOption(this.activeOption);
                return;
            }

            if (!this.allowFreeValue) {
                event.preventDefault();
                this.commitPendingValue();
                this.closeDropdown();
                this.renderOptions();
            }
            return;
        }

        if (event.key === 'Escape') {
            event.preventDefault();
            this.commitPendingValue();
            this.closeDropdown();
            this.renderOptions();
        }
    }

    private moveActiveOption(direction: 1 | -1, visibleOptions: DropdownOption[]): void {
        if (visibleOptions.length === 0) {
            this.activeOption = null;
            this.renderOptions();
            return;
        }

        const currentIndex = this.activeOption
            ? visibleOptions.findIndex((option) => option === this.activeOption)
            : -1;
        const nextIndex = currentIndex === -1
            ? (direction === 1 ? 0 : visibleOptions.length - 1)
            : (currentIndex + direction + visibleOptions.length) % visibleOptions.length;

        this.activeOption = visibleOptions[nextIndex];
        this.renderOptions();
        this.activeOption.element.scrollIntoView({ block: 'nearest' });
    }

    private selectOption(option: DropdownOption, closeDropdown = true): void {
        if (!this.inputElement) return;

        this.selectedOption = option;
        this.activeOption = option;
        this.inputElement.value = option.label;
        this.updateHiddenValue(option.value);

        if (closeDropdown) {
            this.closeDropdown();
        }

        this.renderOptions();
    }

    private commitPendingValue(): void {
        if (!this.inputElement) return;

        const rawValue = this.inputElement.value.trim();
        if (!rawValue) {
            this.selectedOption = null;
            this.activeOption = null;
            this.inputElement.value = '';
            this.updateHiddenValue('');
            return;
        }

        const exactMatch = this.findExactMatch(rawValue);
        if (exactMatch) {
            this.selectOption(exactMatch, false);
            return;
        }

        if (this.allowFreeValue) {
            this.selectedOption = null;
            this.activeOption = null;
            this.updateHiddenValue(rawValue);
            return;
        }

        this.inputElement.value = this.selectedOption?.label || '';
        this.updateHiddenValue(this.selectedOption?.value || '');
    }

    private filterOptions(query: string): void {
        const normalizedQuery = query.trim().toLowerCase();

        this.options.forEach((option) => {
            const matches = !normalizedQuery
                || option.label.toLowerCase().includes(normalizedQuery)
                || option.value.toLowerCase().includes(normalizedQuery);

            option.element.classList.toggle('hidden', !matches);
        });

        const visibleOptions = this.getVisibleOptions();
        if (!visibleOptions.includes(this.activeOption as DropdownOption)) {
            this.activeOption = visibleOptions[0] || this.selectedOption;
        }
    }

    private renderOptions(): void {
        const visibleOptions = this.getVisibleOptions();

        this.options.forEach((option) => {
            const isSelected = this.selectedOption === option;
            const isActive = this.activeOption === option;

            option.element.classList.toggle('bg-primary-50', isSelected || isActive);
            option.element.classList.toggle('ring-1', isActive);
            option.element.classList.toggle('ring-primary-300', isActive);
            option.element.classList.toggle('text-primary-900', isSelected || isActive);
            option.element.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        });

        if (this.optionsContainer) {
            const shouldHide = visibleOptions.length === 0;
            if (shouldHide) {
                this.optionsContainer.classList.add('hidden');
                if (this.inputElement) {
                    this.inputElement.setAttribute('aria-expanded', 'false');
                }
            } else {
                // ensure portal position is updated when visible
                this.positionOptionsContainer();
            }
        }
    }

    private openDropdown(): void {
        if (!this.optionsContainer || this.getVisibleOptions().length === 0) return;

        // Portal the options container to body to avoid modal overflow clipping
        this.portalOptionsToBody();

        this.optionsContainer.classList.remove('hidden');
        this.inputElement?.setAttribute('aria-expanded', 'true');
        this.positionOptionsContainer();
    }

    private closeDropdown(): void {
        if (this.optionsContainer) {
            this.optionsContainer.classList.add('hidden');
            // restore into original DOM position if portaled
            this.restoreOptionsContainer();
        }
        this.inputElement?.setAttribute('aria-expanded', 'false');
    }

    private updateHiddenValue(value: string): void {
        if (this.hiddenInputElement) {
            this.hiddenInputElement.value = value;
        }
    }

    private portalOptionsToBody(): void {
        if (!this.optionsContainer || this.optionsContainer.parentElement === document.body) return;

        this.originalOptionsParent = this.optionsContainer.parentElement;
        this.originalNextSibling = this.optionsContainer.nextSibling;

        // detach and append to body
        document.body.appendChild(this.optionsContainer);

        // add fixed positioning context
        this.optionsContainer.style.position = 'absolute';
        this.optionsContainer.style.zIndex = '9999';

        // attach reposition handlers
        this.repositionHandler = () => this.positionOptionsContainer();
        window.addEventListener('resize', this.repositionHandler);
        window.addEventListener('scroll', this.repositionHandler, true);
    }

    private restoreOptionsContainer(): void {
        if (!this.optionsContainer || !this.originalOptionsParent) return;

        // remove handlers
        if (this.repositionHandler) {
            window.removeEventListener('resize', this.repositionHandler);
            window.removeEventListener('scroll', this.repositionHandler, true);
            this.repositionHandler = null;
        }

        // remove inline styles we added
        this.optionsContainer.style.position = '';
        this.optionsContainer.style.zIndex = '';
        this.optionsContainer.style.left = '';
        this.optionsContainer.style.top = '';
        this.optionsContainer.style.width = '';

        // restore to original location
        if (this.originalNextSibling && this.originalNextSibling.parentNode === this.originalOptionsParent) {
            this.originalOptionsParent.insertBefore(this.optionsContainer, this.originalNextSibling as Node);
        } else {
            this.originalOptionsParent.appendChild(this.optionsContainer);
        }

        this.originalOptionsParent = null;
        this.originalNextSibling = null;
    }

    private positionOptionsContainer(): void {
        if (!this.optionsContainer || !this.inputElement) return;

        const rect = this.inputElement.getBoundingClientRect();
        const scrollY = window.scrollY || window.pageYOffset;
        const scrollX = window.scrollX || window.pageXOffset;

        // Prefer the input width so the dropdown aligns
        const width = Math.max(rect.width, 160);

        this.optionsContainer.style.left = `${rect.left + scrollX}px`;
        this.optionsContainer.style.top = `${rect.bottom + scrollY}px`;
        this.optionsContainer.style.width = `${width}px`;
    }

    private findExactMatch(rawValue: string): DropdownOption | null {
        const normalizedValue = rawValue.trim().toLowerCase();
        if (!normalizedValue) return null;

        return this.options.find((option) => {
            return option.label.toLowerCase() === normalizedValue
                || option.value.toLowerCase() === normalizedValue;
        }) || null;
    }

    private getVisibleOptions(): DropdownOption[] {
        return this.options.filter((option) => !option.element.classList.contains('hidden'));
    }

    private isTruthy(value: string | null): boolean {
        return value === 'true' || value === 'True';
    }

}