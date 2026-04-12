import BaseComponent from "../BaseComponent";

export default class FocusIn extends BaseComponent {
    
    public initialize() {
        this.element.querySelector('input')?.focus();
    }

}
