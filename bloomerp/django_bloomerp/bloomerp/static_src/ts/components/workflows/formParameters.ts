export function parseWorkflowFormValue(value: string): any {
    if (/^-?\d+$/.test(value)) return parseInt(value, 10);

    const trimmed = value.trim();
    if (
        (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
        (trimmed.startsWith('[') && trimmed.endsWith(']'))
    ) {
        try {
            return JSON.parse(trimmed);
        } catch {
            return value;
        }
    }

    return value;
}

export function workflowFormToParameters(form: HTMLFormElement): Record<string, any> {
    const formData = new FormData(form);
    const parameters: Record<string, any> = {};
    const checkboxValues = new Map(
        Array.from(form.querySelectorAll<HTMLInputElement>('input[type="checkbox"][name]'))
            .map((checkbox) => [checkbox.name, checkbox.checked] as const),
    );
    const multiValueFieldNames = new Set(
        Array.from(form.querySelectorAll<HTMLElement>(
            'select[multiple][name], [bloomerp-component="foreign-field-widget"][data-is-m2m="true"][data-field-name]',
        )).map((field) => field.getAttribute('name') || field.dataset.fieldName || ''),
    );

    formData.forEach((value, key) => {
        if (key === 'csrfmiddlewaretoken' || checkboxValues.has(key)) return;
        const parsedValue = parseWorkflowFormValue(String(value));

        if (!(key in parameters)) {
            parameters[key] = multiValueFieldNames.has(key) ? [parsedValue] : parsedValue;
            return;
        }

        const currentValue = parameters[key];
        parameters[key] = Array.isArray(currentValue)
            ? [...currentValue, parsedValue]
            : [currentValue, parsedValue];
    });

    checkboxValues.forEach((checked, name) => {
        parameters[name] = checked;
    });

    return parameters;
}
