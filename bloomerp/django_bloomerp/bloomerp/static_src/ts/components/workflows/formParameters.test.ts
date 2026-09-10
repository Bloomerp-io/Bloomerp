import assert from 'node:assert/strict';
import test from 'node:test';

import { workflowFormToParameters } from './formParameters.ts';

interface TestControl {
    name: string;
    type?: string;
    value: string;
    checked?: boolean;
    multiple?: boolean;
}

class TestFormData {
    private entries: Array<[string, string]>;

    constructor(form: HTMLFormElement) {
        const controls = (form as HTMLFormElement & { testControls: TestControl[] }).testControls;
        this.entries = controls
            .filter((control) => control.type !== 'checkbox' || control.checked)
            .map((control) => [control.name, control.value]);
    }

    forEach(callback: (value: string, key: string) => void): void {
        this.entries.forEach(([key, value]) => callback(value, key));
    }
}

function createForm(controls: TestControl[]): HTMLFormElement {
    return {
        testControls: controls,
        querySelectorAll(selector: string) {
            if (selector === 'input[type="checkbox"][name]') {
                return controls.filter((control) => control.type === 'checkbox');
            }
            return controls.filter((control) => control.multiple).map((control) => ({
                getAttribute: (name: string) => name === 'name' ? control.name : null,
                dataset: {},
            }));
        },
    } as unknown as HTMLFormElement;
}

test('serializes named checkboxes as booleans, including unchecked checkboxes', () => {
    const originalFormData = globalThis.FormData;
    globalThis.FormData = TestFormData as unknown as typeof FormData;

    try {
        const form = createForm([
            { name: 'continue_on_empty', type: 'checkbox', value: 'on', checked: false },
            { name: 'include_archived', type: 'checkbox', value: 'on', checked: true },
        ]);

        assert.deepEqual(workflowFormToParameters(form), {
            continue_on_empty: false,
            include_archived: true,
        });
    } finally {
        globalThis.FormData = originalFormData;
    }
});

test('preserves non-checkbox parsing, multi-values, and CSRF exclusion', () => {
    const originalFormData = globalThis.FormData;
    globalThis.FormData = TestFormData as unknown as typeof FormData;

    try {
        const form = createForm([
            { name: 'csrfmiddlewaretoken', value: 'token' },
            { name: 'limit', value: '12' },
            { name: 'filters', value: '{"active":true}' },
            { name: 'tags', value: 'one', multiple: true },
            { name: 'tags', value: 'two', multiple: true },
        ]);

        assert.deepEqual(workflowFormToParameters(form), {
            limit: 12,
            filters: { active: true },
            tags: ['one', 'two'],
        });
    } finally {
        globalThis.FormData = originalFormData;
    }
});
