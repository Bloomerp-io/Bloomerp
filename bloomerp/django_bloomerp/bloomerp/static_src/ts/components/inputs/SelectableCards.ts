import BaseComponent from '../BaseComponent';

export default class SelectableCards extends BaseComponent {
    private cardElements: HTMLElement[] = [];
    private hiddenValuesContainer: HTMLElement | null = null;
    private searchInput: HTMLInputElement | null = null;
    private selectedValues: Set<string> = new Set<string>();
    private allowMultiple = false;
    private inputName = '';
    private clickHandlers: Array<{ element: HTMLElement; handler: (event: Event) => void }> = [];
    private searchHandler: ((event: Event) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.allowMultiple = this.element.getAttribute('data-allow-multiple') === 'True' || this.element.getAttribute('data-allow-multiple') === 'true';
        this.inputName = this.element.getAttribute('data-name') || 'selectable-cards-value';
        this.cardElements = Array.from(this.element.querySelectorAll<HTMLElement>('[data-value]'));
        this.hiddenValuesContainer = this.element.querySelector<HTMLElement>('[data-selectable-cards-values]');
        this.searchInput = this.element.querySelector<HTMLInputElement>('[data-selectable-cards-search]');

        this.initializeSelectedValues();
        this.bindCardEvents();
        this.bindSearchEvent();
        this.render();
    }

    public destroy(): void {
        this.clickHandlers.forEach(({ element, handler }) => {
            element.removeEventListener('click', handler);
        });
        this.clickHandlers = [];

        if (this.searchInput && this.searchHandler) {
            this.searchInput.removeEventListener('input', this.searchHandler);
        }

        this.searchHandler = null;
        this.searchInput = null;
        this.hiddenValuesContainer = null;
        this.cardElements = [];
        this.selectedValues.clear();
    }

    private initializeSelectedValues(): void {
        if (!this.element) return;

        const initialSingleValue = (this.element.getAttribute('data-value') || '').trim();
        const rawValues = this.element.getAttribute('data-values') || '';

        const parsedValues = this.parseValues(rawValues);

        if (this.allowMultiple) {
            parsedValues.forEach((value) => this.selectedValues.add(value));
            if (initialSingleValue) {
                this.selectedValues.add(initialSingleValue);
            }
            return;
        }

        if (parsedValues.length > 0) {
            this.selectedValues = new Set([parsedValues[0]]);
            return;
        }

        if (initialSingleValue) {
            this.selectedValues = new Set([initialSingleValue]);
        }
    }

    private parseValues(rawValues: string): string[] {
        const trimmed = rawValues.trim();
        if (!trimmed) return [];

        try {
            const parsed = JSON.parse(trimmed);
            if (Array.isArray(parsed)) {
                return parsed.map((value) => String(value)).filter(Boolean);
            }
            if (typeof parsed === 'string' && parsed) {
                return [parsed];
            }
        } catch {
            return trimmed
                .split(',')
                .map((value) => value.trim())
                .filter(Boolean);
        }

        return [];
    }

    private bindCardEvents(): void {
        this.cardElements.forEach((cardElement) => {
            const handler = (event: Event) => {
                event.preventDefault();
                this.toggleSelection(cardElement);
                this.render();
            };

            cardElement.addEventListener('click', handler);
            this.clickHandlers.push({ element: cardElement, handler });
        });
    }

    private bindSearchEvent(): void {
        if (!this.searchInput) return;

        this.searchHandler = () => {
            const query = this.searchInput?.value.toLowerCase().trim() || '';

            this.cardElements.forEach((cardElement) => {
                const cardText = (cardElement.textContent || '').toLowerCase();
                const isVisible = !query || cardText.includes(query);
                cardElement.classList.toggle('hidden', !isVisible);
            });
        };

        this.searchInput.addEventListener('input', this.searchHandler);
    }

    private toggleSelection(cardElement: HTMLElement): void {
        const value = (cardElement.getAttribute('data-value') || '').trim();
        if (!value) return;

        if (this.allowMultiple) {
            if (this.selectedValues.has(value)) {
                this.selectedValues.delete(value);
            } else {
                this.selectedValues.add(value);
            }
            return;
        }

        if (this.selectedValues.has(value)) {
            this.selectedValues.clear();
            return;
        }

        this.selectedValues = new Set([value]);
    }

    private render(): void {
        this.cardElements.forEach((cardElement) => {
            const value = (cardElement.getAttribute('data-value') || '').trim();
            const isSelected = value ? this.selectedValues.has(value) : false;

            cardElement.classList.toggle('border-primary-700', isSelected);
            cardElement.classList.toggle('bg-primary-50', isSelected);
            cardElement.classList.toggle('ring-2', isSelected);
            cardElement.classList.toggle('ring-primary-700', isSelected);

            cardElement.classList.toggle('border-gray-200', !isSelected);
            cardElement.classList.toggle('bg-white', !isSelected);

            const checkElement = cardElement.querySelector<HTMLElement>('[data-selectable-check]');
            if (checkElement) {
                checkElement.classList.toggle('hidden', !isSelected);
                checkElement.classList.toggle('flex', isSelected);
            }
        });

        this.renderHiddenValues();
    }

    private renderHiddenValues(): void {
        if (!this.hiddenValuesContainer) return;

        this.hiddenValuesContainer.innerHTML = '';

        const selectedList = Array.from(this.selectedValues);

        if (selectedList.length === 0) {
            this.hiddenValuesContainer.innerHTML = `<input type="hidden" name="${this.inputName}" value="">`;
            return;
        }

        if (!this.allowMultiple) {
            this.hiddenValuesContainer.innerHTML = `<input type="hidden" name="${this.inputName}" value="${selectedList[0]}">`;
            return;
        }

        selectedList.forEach((value) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = this.inputName;
            input.value = value;
            this.hiddenValuesContainer?.appendChild(input);
        });
    }
}
