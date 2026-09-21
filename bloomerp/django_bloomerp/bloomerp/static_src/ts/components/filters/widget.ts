import { getComponent, initComponents } from '../BaseComponent';
import { BaseWidget } from '../widgets/BaseWidget';
import { t } from '@/utils/i18n';

export function destroyWidgets(root: HTMLElement): void {
    root.querySelectorAll<HTMLElement>('[bloomerp-component]').forEach(node => getComponent(node)?.destroy());
}

export function initializeWidget(root: HTMLElement, value?: unknown): void {
    initComponents(root);
    if (value === undefined) return;
    for (const node of root.querySelectorAll<HTMLElement>('[bloomerp-component]')) {
        const component = getComponent(node);
        if (component instanceof BaseWidget) {
            component.setValue(value, false);
            return;
        }
    }
}

/** Read widget values, optionally allowing incomplete inputs during dependent-form refreshes. */
export function readWidget(root: HTMLElement, validate: boolean = true): unknown {
    // Composite filter editors own their nested value inputs; read only their JSON output.
    const componentOutput = root.querySelector<HTMLInputElement>('input[data-widget-output]');
    if (componentOutput) {
        if (validate && !componentOutput.value) throw new Error(t('Complete every filter condition before applying.'));
        return componentOutput.value;
    }
    // A component owns its descendants; never flatten its internal form controls.
    for (const node of root.querySelectorAll<HTMLElement>('[bloomerp-component]')) {
        const component = getComponent(node);
        if (component instanceof BaseWidget) return component.getValue();
    }
    const controls = Array.from(root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input[name], select[name], textarea[name]'))
        .filter(control => !control.disabled);
    for (const control of controls) if (validate && !control.reportValidity()) throw new Error(t('Please check the filter value.'));
    const read = (control: typeof controls[number]): unknown => {
        if (control instanceof HTMLSelectElement && control.multiple) return Array.from(control.selectedOptions, option => option.value);
        if (control instanceof HTMLInputElement && control.type === 'checkbox') return control.checked;
        return control.value;
    };
    const radio = controls.filter(control => control instanceof HTMLInputElement && control.type === 'radio') as HTMLInputElement[];
    if (radio.length) return radio.find(control => control.checked)?.value ?? null;
    if (controls.length > 1 && controls.every(control => control instanceof HTMLInputElement && control.type === 'checkbox')) {
        return (controls as HTMLInputElement[]).filter(control => control.checked).map(control => control.value);
    }
    if (controls.length === 0) return null;
    if (controls.length === 1) return read(controls[0]);
    // Django MultiWidget controls retain their positional values.
    return controls.map(read);
}
