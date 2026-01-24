import BaseComponent from "../BaseComponent";

export default class DropdownInput extends BaseComponent {
    private inputElement: HTMLInputElement | null = null;

    public initialize(): void {
        this.inputElement = this.element.querySelector('input');
        if (!this.inputElement) {
            console.warn('DropdownInput: No input element found');
        }
    }


}