import type { TemplateField } from "./blocks";
import type { TemplateBuilderVariableCatalog } from "./types";

export function readTemplateFields(scriptId: string | null): TemplateField[] {
    if (!scriptId) return [];

    const scriptEl = document.getElementById(scriptId);
    if (!scriptEl?.textContent) return [];

    try {
        const parsed = JSON.parse(scriptEl.textContent) as TemplateField[];
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        console.error("Failed to parse template builder fields", error);
        return [];
    }
}

export function readVariableCatalog(scriptId: string | null): TemplateBuilderVariableCatalog {
    const emptyCatalog: TemplateBuilderVariableCatalog = {
        modelVariables: [],
        freeVariables: [],
        freeVariableTypes: [],
        injectionMethods: {},
    };
    if (!scriptId) return emptyCatalog;

    const scriptEl = document.getElementById(scriptId);
    if (!scriptEl?.textContent) return emptyCatalog;

    try {
        const parsed = JSON.parse(scriptEl.textContent) as Partial<TemplateBuilderVariableCatalog>;
        return {
            modelVariables: Array.isArray(parsed.modelVariables) ? parsed.modelVariables : [],
            freeVariables: Array.isArray(parsed.freeVariables) ? parsed.freeVariables : [],
            freeVariableTypes: Array.isArray(parsed.freeVariableTypes) ? parsed.freeVariableTypes : [],
            injectionMethods: parsed.injectionMethods || {},
        };
    } catch (error) {
        console.error("Failed to parse template builder variable catalog", error);
        return emptyCatalog;
    }
}
