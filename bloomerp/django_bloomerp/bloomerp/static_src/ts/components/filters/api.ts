import { getCsrfToken } from '@/utils/cookies';
import { t } from '@/utils/i18n';
import type { FieldGroup, FilterScope, LookupDefinition } from './definition';

export class FilterApi {
    private controller = new AbortController();
    constructor(private root: HTMLElement, private scope: FilterScope) {}
    destroy(): void { this.controller.abort(); }

    private async request<T>(endpoint: string, params: Record<string, unknown>, post = false): Promise<T> {
        const configured = this.root.dataset[endpoint];
        if (!configured) throw new Error(t('Filter endpoint is missing.'));
        const url = new URL(configured, location.href);
        const data = { ...this.scope, ...params };
        if (!post) Object.entries(data).forEach(([key, value]) => {
            if (value !== undefined) url.searchParams.set(key, String(value));
        });
        const response = await fetch(url, {
            method: post ? 'POST' : 'GET', credentials: 'same-origin', signal: this.controller.signal,
            ...(post ? { headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() ?? '' }, body: JSON.stringify(data) } : {}),
        });
        if (!response.ok) throw new Error(t('Could not load filter options. Please try again.'));
        return response.json();
    }
    fields(field_path?: string, lookup_id?: string): Promise<FieldGroup[]> {
        return this.request('fieldsUrl', { field_path, lookup_id });
    }
    lookups(field_path: string): Promise<LookupDefinition[]> { return this.request('lookupsUrl', { field_path }); }
    editor(field_path: string, lookup_id: string, value?: unknown): Promise<{ widget: string }> {
        return this.request('valueEditorUrl', { field_path, lookup_id, ...(value === undefined ? {} : { value }) }, true);
    }
}
