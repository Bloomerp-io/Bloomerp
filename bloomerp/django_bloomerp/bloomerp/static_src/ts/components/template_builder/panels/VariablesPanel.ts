import type {
    TemplateBuilderFreeVariable,
    TemplateBuilderModelVariable,
    TemplateBuilderVariableCatalog,
} from "../types";

type VariablesPanelOptions = {
    insertSnippet: (snippet: string) => void;
    onFreeVariablesChange?: (variables: TemplateBuilderFreeVariable[]) => void;
};

export class VariablesPanel {
    private readonly element: HTMLElement;
    private readonly insertSnippet: (snippet: string) => void;
    private readonly onFreeVariablesChange?: (variables: TemplateBuilderFreeVariable[]) => void;
    private catalog: TemplateBuilderVariableCatalog | null = null;

    constructor(element: HTMLElement, options: VariablesPanelOptions) {
        this.element = element;
        this.insertSnippet = options.insertSnippet;
        this.onFreeVariablesChange = options.onFreeVariablesChange;
    }

    render(catalog: TemplateBuilderVariableCatalog): void {
        this.catalog = {
            ...catalog,
            freeVariables: [...catalog.freeVariables],
        };
        this.element.innerHTML = "";
        this.element.appendChild(this.createModelVariableSection(
            "Model variables",
            this.catalog.modelVariables,
            this.catalog
        ));
        this.element.appendChild(this.createFreeVariableSection(
            "Free variables",
            this.catalog.freeVariables,
            this.catalog
        ));
    }

    private createModelVariableSection(
        titleText: string,
        variables: TemplateBuilderModelVariable[],
        catalog: TemplateBuilderVariableCatalog
    ): HTMLElement {
        const section = this.createSection(titleText);
        const list = this.createList();
        if (variables.length === 0) {
            list.appendChild(this.createEmptyVariableMessage("No model variables are available."));
        } else {
            variables.forEach((variable) => {
                list.appendChild(this.createModelVariableItem(variable, catalog));
            });
        }
        section.appendChild(list);
        return section;
    }

    private createFreeVariableSection(
        titleText: string,
        variables: TemplateBuilderFreeVariable[],
        catalog: TemplateBuilderVariableCatalog
    ): HTMLElement {
        const section = this.createSection(titleText);
        section.appendChild(this.createFreeVariableForm(catalog));
        const list = this.createList();
        if (variables.length === 0) {
            list.appendChild(this.createEmptyVariableMessage("No free variables are configured."));
        } else {
            variables.forEach((variable) => {
                list.appendChild(this.createFreeVariableItem(variable, catalog));
            });
        }
        section.appendChild(list);
        return section;
    }

    private createFreeVariableForm(catalog: TemplateBuilderVariableCatalog): HTMLElement {
        const form = document.createElement("div");
        form.className = "mb-3 space-y-2 rounded-xl border border-slate-200 bg-white p-2";

        const labelInput = document.createElement("input");
        labelInput.type = "text";
        labelInput.className = "input w-full";
        labelInput.placeholder = "Variable label";

        const typeInput = document.createElement("select");
        typeInput.className = "input w-full";
        catalog.freeVariableTypes.forEach((type) => {
            const option = document.createElement("option");
            option.value = type.id;
            option.textContent = type.label;
            typeInput.appendChild(option);
        });

        const choicesInput = document.createElement("input");
        choicesInput.type = "text";
        choicesInput.className = "input w-full hidden";
        choicesInput.placeholder = "Choices, comma separated";

        const requiredLabel = document.createElement("label");
        requiredLabel.className = "flex items-center gap-2 text-sm text-slate-700";
        const requiredInput = document.createElement("input");
        requiredInput.type = "checkbox";
        requiredInput.className = "checkbox";
        const requiredText = document.createElement("span");
        requiredText.textContent = "Required";
        requiredLabel.appendChild(requiredInput);
        requiredLabel.appendChild(requiredText);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-secondary btn-sm w-full";
        button.innerHTML = `<i class="fa-solid fa-plus" aria-hidden="true"></i><span>Add variable</span>`;

        typeInput.addEventListener("change", () => {
            const selectedType = catalog.freeVariableTypes.find((type) => type.id === typeInput.value);
            choicesInput.classList.toggle("hidden", !selectedType?.supportsChoices);
        });

        button.addEventListener("click", () => {
            const label = labelInput.value.trim();
            const selectedType = catalog.freeVariableTypes.find((type) => type.id === typeInput.value) || catalog.freeVariableTypes[0];
            if (!label || !selectedType || !this.catalog) return;
            const slug = this.buildUniqueSlug(label, this.catalog.freeVariables);

            this.catalog.freeVariables.push({
                source: "free",
                slug,
                label,
                type: selectedType.id,
                typeLabel: selectedType.label,
                icon: selectedType.icon,
                token: `vars.${slug}`,
                required: requiredInput.checked,
                choices: this.parseChoices(choicesInput.value),
                injectionMethods: selectedType.injectionMethods,
            });
            this.onFreeVariablesChange?.(this.catalog.freeVariables);
            this.render(this.catalog);
        });

        form.appendChild(labelInput);
        form.appendChild(typeInput);
        form.appendChild(choicesInput);
        form.appendChild(requiredLabel);
        form.appendChild(button);
        return form;
    }

    private createSection(titleText: string): HTMLElement {
        const section = document.createElement("section");
        section.className = "template-builder-panel-section";

        const title = document.createElement("h4");
        title.className = "template-builder-panel-title";
        title.textContent = titleText;
        section.appendChild(title);

        return section;
    }

    private createList(): HTMLElement {
        const list = document.createElement("div");
        list.className = "template-builder-variable-list";
        return list;
    }

    private createEmptyVariableMessage(message: string): HTMLElement {
        const empty = document.createElement("p");
        empty.className = "template-builder-help-copy";
        empty.textContent = message;
        return empty;
    }

    private createModelVariableItem(
        variable: TemplateBuilderModelVariable,
        catalog: TemplateBuilderVariableCatalog
    ): HTMLElement {
        return this.createVariableItemShell(
            variable.label,
            variable.fieldTypeLabel,
            variable.icon,
            variable.injectionMethods,
            catalog,
            (methodId) => this.insertModelVariableSnippet(variable, methodId)
        );
    }

    private createFreeVariableItem(
        variable: TemplateBuilderFreeVariable,
        catalog: TemplateBuilderVariableCatalog
    ): HTMLElement {
        const item = this.createVariableItemShell(
            variable.label,
            variable.typeLabel,
            variable.icon,
            variable.injectionMethods,
            catalog,
            (methodId) => this.insertFreeVariableSnippet(variable, methodId)
        );
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "template-builder-variable-action mt-2";
        removeButton.title = "Remove variable";
        removeButton.innerHTML = `<i class="fa-solid fa-trash" aria-hidden="true"></i><span>Remove</span>`;
        removeButton.addEventListener("click", () => this.removeFreeVariable(variable.slug));
        item.appendChild(removeButton);
        return item;
    }

    private createVariableItemShell(
        labelText: string,
        descriptionText: string,
        icon: string,
        methodIds: string[],
        catalog: TemplateBuilderVariableCatalog,
        onMethodClick: (methodId: string) => void
    ): HTMLElement {
        const item = document.createElement("div");
        item.className = "template-builder-variable-item";

        const header = document.createElement("div");
        header.className = "template-builder-variable-item-header";
        header.appendChild(this.createIconBadge(icon, "template-builder-variable-item-icon"));

        const body = document.createElement("span");
        body.className = "template-builder-variable-item-body";

        const label = document.createElement("span");
        label.className = "template-builder-variable-label";
        label.textContent = labelText;

        const description = document.createElement("span");
        description.className = "template-builder-variable-description";
        description.textContent = descriptionText;

        body.appendChild(label);
        body.appendChild(description);
        header.appendChild(body);
        item.appendChild(header);

        const actions = document.createElement("div");
        actions.className = "template-builder-variable-actions";
        methodIds.forEach((methodId) => {
            const method = catalog.injectionMethods[methodId];
            if (!method) return;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "template-builder-variable-action";
            button.title = method.description || method.label;
            button.innerHTML = `<i class="${method.icon}" aria-hidden="true"></i><span>${method.label}</span>`;
            button.addEventListener("click", () => onMethodClick(methodId));
            actions.appendChild(button);
        });
        item.appendChild(actions);

        return item;
    }

    private createIconBadge(icon?: string, badgeClass = ""): HTMLSpanElement {
        const badge = document.createElement("span");
        badge.className = `template-builder-block-item-icon ${badgeClass}`.trim();

        const iconEl = document.createElement("i");
        iconEl.className = icon || "fa-solid fa-square-plus";
        iconEl.setAttribute("aria-hidden", "true");
        badge.appendChild(iconEl);

        return badge;
    }

    private insertModelVariableSnippet(variable: TemplateBuilderModelVariable, methodId: string): void {
        const relatedFields = variable.relatedFields || [];
        const defaultFields = relatedFields.slice(0, 3).map((field) => field.name).join(",");
        let snippet = `{{ ${variable.token} }}`;

        if (methodId === "formatted_date") {
            snippet = `{{ ${variable.token}|date:"d/m/Y" }}`;
        } else if (methodId === "yes_no") {
            snippet = `{{ ${variable.token}|yesno:"Yes,No" }}`;
        } else if (methodId === "nested_field") {
            const selectedField = window.prompt("Related field", relatedFields[0]?.name || "");
            if (!selectedField) return;
            snippet = `{{ ${variable.token}.${selectedField.trim()} }}`;
        } else if (methodId === "loop") {
            snippet = `{% for item in ${variable.token}.all %}\n{{ item }}\n{% endfor %}`;
        } else if (methodId === "list") {
            snippet = `{% for item in ${variable.token}.all %}\n- {{ item }}\n{% endfor %}`;
        } else if (methodId === "table") {
            const selectedFields = window.prompt("Table fields, comma separated", defaultFields);
            if (!selectedFields) return;
            snippet = `{% document_table ${variable.token}.all "${selectedFields.trim()}" %}`;
        } else if (methodId === "count") {
            snippet = `{{ ${variable.token}.count }}`;
        }

        this.insertSnippet(snippet);
    }

    private insertFreeVariableSnippet(variable: TemplateBuilderFreeVariable, methodId: string): void {
        let snippet = `{{ ${variable.token} }}`;
        if (methodId === "formatted_date") {
            snippet = `{{ ${variable.token}|date:"d/m/Y" }}`;
        } else if (methodId === "yes_no") {
            snippet = `{{ ${variable.token}|yesno:"Yes,No" }}`;
        }
        this.insertSnippet(snippet);
    }

    private removeFreeVariable(slug: string): void {
        if (!this.catalog) return;
        this.catalog.freeVariables = this.catalog.freeVariables.filter((variable) => variable.slug !== slug);
        this.onFreeVariablesChange?.(this.catalog.freeVariables);
        this.render(this.catalog);
    }

    private normalizeSlug(value: string): string {
        return value
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9_]+/g, "_")
            .replace(/^_+|_+$/g, "");
    }

    private buildUniqueSlug(label: string, variables: TemplateBuilderFreeVariable[]): string {
        const baseSlug = this.normalizeSlug(label) || "variable";
        const usedSlugs = new Set(variables.map((variable) => variable.slug));
        if (!usedSlugs.has(baseSlug)) return baseSlug;

        let suffix = 2;
        while (usedSlugs.has(`${baseSlug}_${suffix}`)) {
            suffix += 1;
        }
        return `${baseSlug}_${suffix}`;
    }

    private parseChoices(value: string): Array<{ value: string; label: string }> {
        return value
            .split(",")
            .map((choice) => choice.trim())
            .filter(Boolean)
            .map((choice) => {
                const [rawValue, rawLabel] = choice.split(":");
                const choiceValue = (rawValue || "").trim();
                return {
                    value: choiceValue,
                    label: (rawLabel || choiceValue).trim(),
                };
            });
    }
}
