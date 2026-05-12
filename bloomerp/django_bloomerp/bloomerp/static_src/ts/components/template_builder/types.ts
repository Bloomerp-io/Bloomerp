export type TemplateBuilderTab = "blocks" | "styles" | "layers" | "settings" | "variables";

export type TemplateBuilderPageSize = "A4" | "Letter" | "A3";
export type TemplateBuilderPageOrientation = "portrait" | "landscape";

export type TemplateBuilderPageSettings = {
    pageSize: TemplateBuilderPageSize;
    orientation: TemplateBuilderPageOrientation;
    marginInches: number;
};

export type TemplateBuilderInjectionMethod = {
    id: string;
    label: string;
    icon: string;
    description: string;
    requiresFieldSelection?: boolean;
};

export type TemplateBuilderRelatedField = {
    name: string;
    label: string;
    fieldType: string;
    fieldTypeLabel: string;
    icon: string;
    token: string;
};

export type TemplateBuilderModelVariable = {
    source: "model";
    name: string;
    label: string;
    fieldType: string;
    fieldTypeLabel: string;
    icon: string;
    token: string;
    rootName?: string;
    contentTypeId?: number;
    injectionMethods: string[];
    relatedFields: TemplateBuilderRelatedField[];
};

export type TemplateBuilderFreeVariable = {
    source: "free";
    slug: string;
    label: string;
    type: string;
    typeLabel: string;
    icon: string;
    token: string;
    required: boolean;
    choices?: Array<{ value: string; label: string }>;
    injectionMethods: string[];
};

export type TemplateBuilderFreeVariableType = {
    id: string;
    label: string;
    icon: string;
    supportsChoices: boolean;
    injectionMethods: string[];
};

export type TemplateBuilderVariableCatalog = {
    modelVariables: TemplateBuilderModelVariable[];
    freeVariables: TemplateBuilderFreeVariable[];
    freeVariableTypes: TemplateBuilderFreeVariableType[];
    injectionMethods: Record<string, TemplateBuilderInjectionMethod>;
};
