import BaseComponent from "../BaseComponent";

export default class PermissionCheckboxes extends BaseComponent {
    private checkboxes: HTMLInputElement[] = [];
    private allCheckbox: HTMLInputElement | null = null;
    private individualCheckboxes: HTMLInputElement[] = [];
    private allCheckboxChangeHandler: (() => void) | null = null;
    private individualChangeHandlers: ((() => void) | null)[] = [];
    private inputName: string = '';
    private onchangeCallback: (() => void) | null = null;


    public initialize(): void {
        // Get the input name from data attribute
        this.inputName = this.element?.getAttribute('data-name') || '';

        this.checkboxes = Array.from(this.element.querySelectorAll(`input[name="${this.inputName}"]`)) as HTMLInputElement[];
        this.allCheckbox = this.checkboxes.find(cb => cb.value === '__all__') || null;
        this.individualCheckboxes = this.checkboxes.filter(cb => cb.value !== '__all__');

        if (!this.allCheckbox) return;

        const updateAllCheckbox = () => {
            const allChecked = this.individualCheckboxes.every(cb => cb.checked);
            this.allCheckbox!.checked = allChecked;
            this.onchangeCallback?.();
        };

        this.allCheckboxChangeHandler = () => {
            this.individualCheckboxes.forEach(cb => cb.checked = this.allCheckbox!.checked);
            this.onchangeCallback?.();
        };

        this.allCheckbox.addEventListener('change', this.allCheckboxChangeHandler);

        this.individualChangeHandlers = this.individualCheckboxes.map(cb => {
            const handler = updateAllCheckbox;
            cb.addEventListener('change', handler);
            return handler;
        });

        updateAllCheckbox();
    }

    public destroy(): void {
        if (this.allCheckbox && this.allCheckboxChangeHandler) {
            this.allCheckbox.removeEventListener('change', this.allCheckboxChangeHandler);
        }

        this.individualChangeHandlers.forEach((handler, index) => {
            if (handler && this.individualCheckboxes[index]) {
                this.individualCheckboxes[index].removeEventListener('change', handler);
            }
        });

        this.checkboxes = [];
        this.allCheckbox = null;
        this.individualCheckboxes = [];
        this.allCheckboxChangeHandler = null;
        this.individualChangeHandlers = [];
    }

    /**
     * Returns the selected values of the permission checkboxes
     * (excluding __all__)
     */
    public getValues():Array<string> {
        return this.individualCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
    }

    /**
     * Resets all permission checkboxes to unchecked state
     */
    public reset(): void {
        this.checkboxes.forEach(cb => cb.checked = false);
    }

    /**
     * Sets the onchange callback function
     */
    public setOnChange(callback: () => void): void {
        this.onchangeCallback = callback;
    }
}