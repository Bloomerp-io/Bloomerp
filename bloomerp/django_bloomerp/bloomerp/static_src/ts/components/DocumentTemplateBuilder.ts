import { $createTextNode } from "lexical";
import BaseComponent, { getComponent } from "./BaseComponent";
import { BloomerpTextEditor } from "./text_editor/BloomerpTextEditor";
import ForeignFieldWidget from "./widgets/ForeignFieldWidget";
import getSdk from "@/sdk/getSdk";
import CodeEditorWidget from "./widgets/CodeEditorWidget";

type InjectionMethod = {
    id: string;
    label: string;
    icon: string;
    description: string;
};

type FreeVariable = {
    slug: string;
    label: string;
    type: string;
    typeLabel: string;
    icon: string;
    required: boolean;
    choices: Array<{ value: string; label: string }>;
    injectionMethods: InjectionMethod[];
};

type FreeVariableTypeDefinition = {
    id: string;
    label: string;
    icon: string;
    supportsChoices: boolean;
    injectionMethods: InjectionMethod[];
};

/**
 * Returns the default injection method
 */
function getDefaultInjectionMethod() : InjectionMethod {
    return {
        id: 'value',
        label: 'Value',
        icon: 'fa-solid fa-code',
        description: 'Insert the value.',
    }
}

/**
 * Returns a known injection method
 * @param methodId 
 */
function getKnownInjectionMethod(methodId:string) : InjectionMethod {
    const knownMethods:Record<string, InjectionMethod> = {
        value: getDefaultInjectionMethod(),
        formatted_date: {
            id: 'formatted_date',
            label: 'Formatted date',
            icon: 'fa-solid fa-calendar-day',
            description: 'Insert the value with a date format.',
        },
        yes_no: {
            id: 'yes_no',
            label: 'Yes / no',
            icon: 'fa-solid fa-circle-check',
            description: 'Render a boolean value as yes or no.',
        },
    }

    return knownMethods[methodId] || {
        id: methodId,
        label: methodId.replace(/_/g, ' '),
        icon: 'fa-solid fa-code',
        description: '',
    }
}

/**
 * Returns injection methods from a catalog element
 * @param element 
 */
function getInjectionMethods(element:HTMLElement) : InjectionMethod[] {
    const methods = Array.from(element.querySelectorAll('[data-injection-method]')).map((methodElement)=> {
        const method = methodElement as HTMLElement
        return {
            id: method.dataset.id || 'value',
            label: method.dataset.label || 'Value',
            icon: method.dataset.icon || 'fa-solid fa-code',
            description: method.dataset.description || '',
        }
    })

    return methods.length ? methods : [getDefaultInjectionMethod()]
}

/**
 * Returns a free variable type definition from the select input
 * @param freeVariableType 
 * @param type 
 */
function getFreeVariableTypeDefinition(freeVariableType:HTMLSelectElement, type:string) : FreeVariableTypeDefinition|null {
    const option = Array.from(freeVariableType.options).find((item)=>item.value === type)
    if (!option) {return null}

    return {
        id: option.value,
        label: option.textContent?.trim() || option.value,
        icon: option.dataset.icon || 'fa-solid fa-cubes',
        supportsChoices: option.dataset.supportsChoices === 'true',
        injectionMethods: (option.dataset.injectionMethods || 'value')
            .split(',')
            .filter(Boolean)
            .map((methodId)=>getKnownInjectionMethod(methodId)),
    }
}

/**
 * Parses the choices input into the model json format
 * @param value 
 */
function parseChoices(value:string) : Array<{ value: string; label: string }> {
    return value
        .split(',')
        .map((choice)=>choice.trim())
        .filter(Boolean)
        .map((choice)=>{
            const [rawValue, rawLabel] = choice.split(':')
            const choiceValue = (rawValue || '').trim()
            return {
                value: choiceValue,
                label: (rawLabel || choiceValue).trim(),
            }
        })
        .filter((choice)=>Boolean(choice.value))
}

/**
 * Returns a readable choices summary
 * @param choices 
 */
function getChoicesDescription(choices:Array<{ value: string; label: string }>) {
    if (!choices.length) {return ''}
    return `${choices.length} ${choices.length === 1 ? 'choice' : 'choices'}`
}

/**
 * Normalizes a variable slug
 * @param value 
 */
function normalizeSlug(value:string) {
    return value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, '_')
        .replace(/^_+|_+$/g, '')
}

/**
 * Returns a unique slug for a free variable
 * @param value 
 * @param freeVariables 
 */
function getUniqueSlug(value:string, freeVariables:FreeVariable[]) {
    const baseSlug = normalizeSlug(value) || 'variable'
    const usedSlugs = new Set(freeVariables.map((variable)=>variable.slug))
    if (!usedSlugs.has(baseSlug)) {return baseSlug}

    let suffix = 2
    while (usedSlugs.has(`${baseSlug}_${suffix}`)) {
        suffix += 1
    }
    return `${baseSlug}_${suffix}`
}

/**
 * Creates a variable div
 * @param label the label
 * @param icon the icon
 * @returns the variable div
 */
function createVariableDiv(
    label:string,
    icon:string,
    description:string,
    injectionMethods:InjectionMethod[],
    onInjectionMethodClick:(methodId:string)=>void,
    onRemove?:()=>void,
) : HTMLDivElement {
    // Create wrapper div
    const containerDiv = document.createElement('div')
    containerDiv.classList = 'border border-gray-200 rounded-xl p-3 flex-col flex mb-2'

    // Create icon and label div
    const iconWrapper = document.createElement('span')
    iconWrapper.className = 'w-9 h-9 rounded-xl bg-primary/8 inline-flex items-center justify-center flex-shrink-0'

    const iconDiv = document.createElement('i')
    iconDiv.className = icon + " text-primary text-base leading-none"
    iconWrapper.appendChild(iconDiv)

    const labelDiv = document.createElement('div')
    labelDiv.className = 'text-sm font-medium text-gray-700'
    labelDiv.textContent = label

    const descriptionDiv = document.createElement('div')
    descriptionDiv.className = 'text-xs text-gray-500'
    descriptionDiv.textContent = description

    const labelWrapper = document.createElement('div')
    labelWrapper.className = 'flex flex-col'
    labelWrapper.appendChild(labelDiv)
    labelWrapper.appendChild(descriptionDiv)


    const anotherDiv = document.createElement('div')
    anotherDiv.className = 'flex gap-2 items-center mb-2'

    anotherDiv.appendChild(iconWrapper)
    anotherDiv.appendChild(labelWrapper)
    
    containerDiv.appendChild(anotherDiv)

    const actionsDiv = document.createElement('div')
    actionsDiv.className = 'flex flex-wrap gap-1'
    injectionMethods.forEach((injectionMethod)=>{
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'badge bg-primary/8 badge-xs border-0 cursor-pointer'
        button.title = injectionMethod.description
        button.innerHTML = `<i class="${injectionMethod.icon}"></i> ${injectionMethod.label}`
        button.addEventListener('click', ()=>onInjectionMethodClick(injectionMethod.id))
        actionsDiv.appendChild(button)
    })

    if (onRemove) {
        const removeButton = document.createElement('button')
        removeButton.type = 'button'
        removeButton.className = 'badge badge-danger badge-xs'
        removeButton.innerHTML = '<i class="fa-solid fa-trash"></i> Remove'
        removeButton.addEventListener('click', ()=>onRemove())
        actionsDiv.appendChild(removeButton)
    }

    containerDiv.appendChild(actionsDiv)

    return containerDiv
}

export class DocumentTemplateBuilder extends BaseComponent {
    private editor: BloomerpTextEditor;
    private pageContainer: HTMLDivElement;
    private pageContentSection:HTMLDivElement;
    private pageHeaderSection:HTMLDivElement;
    private currentPageSize: 'A4' | 'A3' | 'Letter' = 'A4';
    private currentPageOrientation: 'landscape' | 'portrait' = 'portrait';
    
    private freeVariables: FreeVariable[] = [];
    private freeVariableField: CodeEditorWidget|null = null;
    private freeVariableInput: HTMLTextAreaElement|null = null;


    public initialize(): void {
        this.editor = getComponent(
            this.element.querySelector('[bloomerp-component="bloomerp-text-editor"]') as HTMLElement
        ) as BloomerpTextEditor;


        // Get page container
        this.pageContainer = this.element.querySelector('#page-container')
        this.pageContentSection = this.element.querySelector('#page-content-section')
        this.pageHeaderSection = this.element.querySelector('#page-header-section')

        // Clicking somewhere in pageContainer should focus on editor
        this.pageContainer.addEventListener('click', ()=>{this.editor.editor.focus()})

        // Apply initial styling
        const pageMarginField = this.getFormField('page_margin')
        this.applyPageMargin(pageMarginField.value)
        pageMarginField.addEventListener('change', ()=>{
            this.applyPageMargin(pageMarginField.value)
        })

        // Apply page size
        const pageSizeField = this.getFormField('page_size')
        this.applyPageSize(pageSizeField.value)
        pageSizeField.addEventListener('change', ()=>{
            this.applyPageSize(pageSizeField.value)
        })

        const pageOrientationField = this.getFormField('page_orientation')
        this.applyPageOrientation(pageOrientationField.value)
        pageOrientationField.addEventListener('change', ()=>{
            this.applyPageOrientation(pageOrientationField.value)
        })

        // Apply page header
        const pageHeaderField = getComponent(this.getFormField('template_header')) as ForeignFieldWidget;
        this.applyPageHeader(pageHeaderField.getValue() as string|null)
        pageHeaderField.element.addEventListener('bloomerp:widget-change', ()=>{this.applyPageHeader(pageHeaderField.getValue() as string|null)})

        // Apply page styling
        const pageStyling = getComponent(this.getFormField('styling')) as ForeignFieldWidget;
        this.applyPageStyling(pageStyling.getValue() as string|null)

        // Render content types
        const contentTypes = getComponent(this.getFormField('content_types')) as ForeignFieldWidget;
        this.renderContentTypes(contentTypes.getValue() as string[])
        contentTypes.element.addEventListener('bloomerp:widget-change', ()=>{this.renderContentTypes(contentTypes.getValue() as string[])})

        // Free variables
        this.freeVariableInput = this.getFormField('free_variables') as HTMLTextAreaElement|null;
        const freeVariableComponent = this.freeVariableInput?.closest('[bloomerp-component="code-editor-widget"]') as HTMLElement|null;
        this.freeVariableField = freeVariableComponent ? getComponent(freeVariableComponent) as CodeEditorWidget : null;
        this.freeVariables = this.readFreeVariables();
        this.renderFreeVariables();
        this.syncFreeVariablesInput();
        
        const freeVariableLabel = this.getFormField('free_variable_label')
        const freeVariableType = this.getFormField('free_variable_type');
        const freeVariableChoices = this.getFormField('free_variable_choices');
        const freeVariableRequired = this.getFormField('free_variable_required')
        const freeVariableAddBtn = this.element.querySelector('#add-free-variable-button')
        const syncChoicesVisibility = () => {
            const typeDefinition = getFreeVariableTypeDefinition(freeVariableType, freeVariableType.value)
            freeVariableChoices.classList.toggle('hidden', !typeDefinition?.supportsChoices)
        }

        syncChoicesVisibility()
        freeVariableType.addEventListener('change', syncChoicesVisibility)

        freeVariableAddBtn.addEventListener('click', ()=>{
            this.addFreeVariable(
                freeVariableLabel.value,
                freeVariableType.value,
                freeVariableRequired.checked,
                freeVariableChoices.value,
            )
            freeVariableLabel.value = '';
            freeVariableChoices.value = '';
            freeVariableRequired.checked = false;
        })

    }


    private buildVariableNode(token: string) {
        return $createTextNode(`{{ ${token} }}`);
    }

    /**
     * Renders the document template header
     */
    private applyPageHeader(headerId:string|null) : void {
        const sdk = getSdk();
        const headerSection = this.pageHeaderSection
        headerSection.innerHTML = ''
        headerSection.style.padding = ''
        headerSection.style.boxSizing = ''

        if (headerId) {
            sdk.documentTemplateHeaders.retrieve(headerId).then((header)=>{
                headerSection.style.paddingTop = `${header.margin_top}in`
                headerSection.style.paddingRight = `${header.margin_right}in`
                headerSection.style.paddingBottom = `${header.margin_bottom}in`
                headerSection.style.paddingLeft = `${header.margin_left}in`
                headerSection.style.boxSizing = 'border-box'

                const image = document.createElement('img')
                image.src = header.header
                image.alt = header.name
                image.style.display = 'block'
                image.style.width = '100%'
                image.style.maxWidth = '100%'
                image.style.minHeight = `${header.height}in`
                image.style.objectFit = 'contain'
                image.style.objectPosition = 'left top'

                // Also change the page margin
                

                headerSection.appendChild(image)
                return
        })
        
        }
    }

    /**
     * Renders the content types
     * @param contentTypeIds 
     */
    private renderContentTypes(contentTypeIds:string[]) {
        if (!contentTypeIds) {return}

        let catalogUrl = this.element.dataset.catalogUrl +"?";
        contentTypeIds.forEach((v)=>{
            catalogUrl+='content_types='+encodeURIComponent(v) +"&"
        })

        fetch(catalogUrl, {credentials: 'same-origin'})
            .then((response) => response.ok ? response.text() : '')
            .then((html) => this.renderModelVariables(html))
    }

    /**
     * Add's extra styling to the document
     * @param styling the content of the styling css
     */
    private applyPageStyling(styling:string) : void{
        const sdk = getSdk();
    }

    /**
     * Applies page orientation to the editor
     */
    private applyPageOrientation(orientation:'landscape' | 'portrait') {
        this.currentPageOrientation = orientation
        this.applyPageDimensions()
    }

    /**
     * Applies page margin
     */
    private applyPageMargin(margin:number|string) {
        this.pageContentSection.style.padding = `${margin.toString()}in`
    }

    /**
     * Returns a form field based on the ID
     * @param id 
     */
    private getFormField(id:string) : HTMLInputElement | any {
        return this.element.querySelector('#id_'+id)
    }

    /**
     * Applies the correct page size to the container by tweaking the margins
     */
    private applyPageSize(size:'A4' | 'A3' | 'Letter') {
        this.currentPageSize = size

        this.applyPageDimensions()
    }

    private applyPageDimensions() {
        let width = ''
        let height = ''

        switch (this.currentPageSize) {
            case 'A4':
                width = '217mm'
                height = '297mm'
                break
            case 'A3':
                width = '297mm'
                height = '420mm'
                break
            case 'Letter':
                width = '8.5in'
                height = '11in'
                break
        }

        if (this.currentPageOrientation === 'landscape') {
            this.pageContainer.style.width = height
            this.pageContainer.style.minHeight = width
            return
        }

        this.pageContainer.style.width = width
        this.pageContainer.style.minHeight = height
    }

    /**
     * Add's a free variable
     * @param label 
     * @param type 
     * @param required 
     */
    private addFreeVariable(
        label:string,
        type:string,
        required:boolean,
        choices:string,
    ) {
        const trimmedLabel = label.trim();
        const typeDefinition = getFreeVariableTypeDefinition(this.getFormField('free_variable_type') as HTMLSelectElement, type);
        if (!trimmedLabel || !typeDefinition) {return}

        const parsedChoices = typeDefinition.supportsChoices ? parseChoices(choices) : []
        const slug = getUniqueSlug(trimmedLabel, this.freeVariables);
        this.freeVariables.push({
            slug,
            label: trimmedLabel,
            type: typeDefinition.id,
            typeLabel: typeDefinition.label,
            icon: typeDefinition.icon,
            required,
            choices: parsedChoices,
            injectionMethods: typeDefinition.injectionMethods,
        })

        this.syncFreeVariablesInput()
        this.renderFreeVariables()
    }

    /**
     * Renders the free variables
     */
    private renderFreeVariables() {
        const freeVariableDiv = this.element.querySelector('#free-variable-content')
        freeVariableDiv.innerHTML = ''

        this.freeVariables.forEach((variable)=>{
            const choiceDescription = getChoicesDescription(variable.choices)
            const variableDiv = createVariableDiv(
                variable.label,
                variable.icon,
                choiceDescription ? `${variable.typeLabel} · ${choiceDescription}` : variable.typeLabel,
                variable.injectionMethods,
                (methodId) => this.insertVariable(variable.slug, methodId, true),
                () => this.removeFreeVariable(variable.slug),
            )
            freeVariableDiv.appendChild(variableDiv)
        })
    }

    /**
     * Renders the model variables from the data returned by the catalog endpoint
     * @param html 
     */
    private renderModelVariables(html:string) {
        const contentTypeResults = this.element.querySelector('#content-type-results')
        contentTypeResults.innerHTML = ''

        const template = document.createElement('template')
        template.innerHTML = html

        template.content.querySelectorAll('[data-model-variable]').forEach((element)=>{
            const variableElement = element as HTMLElement
            const token = variableElement.dataset.token
            if (!token) {return}

            const variableDiv = createVariableDiv(
                variableElement.dataset.label || token,
                variableElement.dataset.icon || 'fa-solid fa-cubes',
                variableElement.dataset.fieldTypeLabel || '',
                getInjectionMethods(variableElement),
                (methodId) => this.insertVariable(token, methodId, false),
            )
            contentTypeResults.appendChild(variableDiv)
        })
    }

    /**
     * Reads the free variables from the hidden json field
     */
    private readFreeVariables() : FreeVariable[] {
        const rawValue = this.freeVariableField?.getValue() || this.freeVariableInput?.value || '[]';
        let parsedValue:unknown = []

        try {
            parsedValue = JSON.parse(rawValue || '[]')
        } catch {
            parsedValue = []
        }

        if (!Array.isArray(parsedValue)) {return []}

        return parsedValue.map((item)=>{
            const typeDefinition = getFreeVariableTypeDefinition(this.getFormField('free_variable_type') as HTMLSelectElement, String(item.type || 'text'))
            const label = String(item.label || item.slug || '').trim()
            const slug = normalizeSlug(String(item.slug || label))

            if (!label || !slug) {return null}

            return {
                slug,
                label,
                type: String(item.type || typeDefinition?.id || 'text'),
                typeLabel: typeDefinition?.label || String(item.type || 'text'),
                icon: typeDefinition?.icon || 'fa-solid fa-cubes',
                required: Boolean(item.required),
                choices: Array.isArray(item.choices) ? item.choices : [],
                injectionMethods: typeDefinition?.injectionMethods || [getDefaultInjectionMethod()],
            }
        }).filter((item): item is FreeVariable => item !== null)
    }

    /**
     * Updates the hidden json field with the free variables
     */
    private syncFreeVariablesInput() {
        const value = JSON.stringify(this.freeVariables.map((variable)=>({
            slug: variable.slug,
            label: variable.label,
            type: variable.type,
            required: variable.required,
            choices: variable.choices,
        })), null, 2)

        if (this.freeVariableField) {
            this.freeVariableField.setValue(value)
            return
        }

        if (this.freeVariableInput) {
            this.freeVariableInput.value = value
        }
    }

    /**
     * Removes a free variable
     * @param slug 
     */
    private removeFreeVariable(slug:string) {
        this.freeVariables = this.freeVariables.filter((variable)=>variable.slug !== slug)
        this.syncFreeVariablesInput()
        this.renderFreeVariables()
    }

    /**
     * Inserts a variable into the editor
     * @param token 
     * @param methodId 
     * @param isFreeVariable 
     */
    private insertVariable(token:string, methodId:string, isFreeVariable:boolean) {
        const variableToken = isFreeVariable ? `vars.${token}` : token
        let snippet = `{{ ${variableToken} }}`

        if (methodId === 'formatted_date') {
            snippet = `{{ ${variableToken}|date:"d/m/Y" }}`
        } else if (methodId === 'yes_no') {
            snippet = `{{ ${variableToken}|yesno:"Yes,No" }}`
        } else if (methodId === 'loop') {
            snippet = `{% for item in ${variableToken}.all %}\n{{ item }}\n{% endfor %}`
        } else if (methodId === 'list') {
            snippet = `{% for item in ${variableToken}.all %}\n- {{ item }}\n{% endfor %}`
        } else if (methodId === 'count') {
            snippet = `{{ ${variableToken}.count }}`
        } else if (methodId === 'table') {
            const fields = window.prompt('Table fields, comma separated', '')
            if (!fields) {return}
            snippet = `{% document_table ${variableToken}.all "${fields.trim()}" %}`
        } else if (methodId === 'nested_field') {
            const field = window.prompt('Related field', '')
            if (!field) {return}
            snippet = `{{ ${variableToken}.${field.trim()} }}`
        }

        this.editor.insertNode(() => $createTextNode(snippet))
    }

}
