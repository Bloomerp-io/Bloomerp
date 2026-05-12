import BaseComponent from "./BaseComponent";

export default class FocusOnForm extends BaseComponent {
    public initialize(): void {
        if (!this.element) return;
        
        const firstInput = this.element.querySelector<HTMLInputElement | HTMLSelectElement>(
            'input, select'
        );
        console.log()       
        if (firstInput) {
            firstInput.focus();
        }
    }
}