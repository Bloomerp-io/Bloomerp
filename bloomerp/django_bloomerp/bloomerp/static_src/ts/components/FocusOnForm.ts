import BaseComponent from "./BaseComponent";

export default class FocusOnForm extends BaseComponent {
    public initialize(): void {
        if (!this.element) return;
        
        const isInputOrSelect = this.element instanceof HTMLInputElement || this.element instanceof HTMLSelectElement;
        if (isInputOrSelect) {
            (this.element as HTMLInputElement | HTMLSelectElement).focus();
            return;
        }

        const firstInput = this.element.querySelector<HTMLInputElement | HTMLSelectElement>(
            'input, select'
        );
        if (firstInput) {
            firstInput.focus();
        }
    }
}