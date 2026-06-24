import { $createTextNode, $getSelection } from "lexical";
import BaseComponent, { getComponent } from "./BaseComponent";
import { BloomerpTextEditor } from "./text_editor/BloomerpTextEditor";
import ForeignFieldWidget from "./widgets/ForeignFieldWidget";
import getSdk from "@/sdk/getSdk";
import CodeEditorWidget from "./widgets/CodeEditorWidget";
import getGeneralModal, { getModal } from "@/utils/modals";
import { edit } from "ace-builds";
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./text_editor/utils/wordSelector";
import htmx from "htmx.org";
import showMessage from "@/utils/messages";
import { MessageType } from "./UiMessage";

const AUTO_SAVE_INTERVAL_MS = 5000;

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

type VariablePickerEntry = {
    id: string;
    sourceLabel: string;
    label: string;
    description: string;
    icon: string;
    token: string;
    isFreeVariable: boolean;
    injectionMethods: InjectionMethod[];
    searchText: string;
};

type VariablePickerItem = {
    entry: VariablePickerEntry;
    element: HTMLDivElement;
};

type VariablePickerLayout = {
    root: HTMLDivElement;
    searchInput: HTMLInputElement;
    emptyState: HTMLParagraphElement;
    results: HTMLDivElement;
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

function getFreeVariableDescription(variable:FreeVariable) {
    const choiceDescription = getChoicesDescription(variable.choices)
    return choiceDescription ? `${variable.typeLabel} · ${choiceDescription}` : variable.typeLabel
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

function createVariablePickerEntry(args: {
    id: string;
    sourceLabel: string;
    label: string;
    description: string;
    icon: string;
    token: string;
    isFreeVariable: boolean;
    injectionMethods: InjectionMethod[];
}) : VariablePickerEntry {
    const searchText = [
        args.sourceLabel,
        args.label,
        args.description,
        args.token,
        ...args.injectionMethods.map((method) => method.label),
    ].join(' ').toLowerCase()

    return {
        ...args,
        searchText,
    }
}

function createModelVariablePickerEntry(variableElement:HTMLElement) : VariablePickerEntry|null {
    const token = variableElement.dataset.token
    if (!token) {return null}

    return createVariablePickerEntry({
        id: `model:${token}`,
        sourceLabel: variableElement.dataset.contentTypeLabel || 'Model variable',
        label: variableElement.dataset.label || token,
        description: variableElement.dataset.fieldTypeLabel || '',
        icon: variableElement.dataset.icon || 'fa-solid fa-cubes',
        token,
        isFreeVariable: false,
        injectionMethods: getInjectionMethods(variableElement),
    })
}

function createFreeVariablePickerEntry(variable:FreeVariable) : VariablePickerEntry {
    return createVariablePickerEntry({
        id: `free:${variable.slug}`,
        sourceLabel: 'Free variable',
        label: variable.label,
        description: getFreeVariableDescription(variable),
        icon: variable.icon,
        token: variable.slug,
        isFreeVariable: true,
        injectionMethods: variable.injectionMethods,
    })
}

function matchesVariablePickerEntry(entry:VariablePickerEntry, query:string) {
    const normalizedQuery = query.trim().toLowerCase()
    return !normalizedQuery || entry.searchText.includes(normalizedQuery)
}

function getWrappedIndex(currentIndex:number, delta:1|-1, length:number) {
    if (length === 0) {return -1}
    if (currentIndex === -1) {
        return delta === 1 ? 0 : length - 1
    }
    return (currentIndex + delta + length) % length
}

function createVariablePickerLayout() : VariablePickerLayout {
    const root = document.createElement('div')
    root.className = 'space-y-4'

    const searchInput = document.createElement('input')
    searchInput.type = 'text'
    searchInput.className = 'input w-full'
    searchInput.placeholder = 'Search variables'
    searchInput.setAttribute('aria-label', 'Search variables')
    root.appendChild(searchInput)

    const emptyState = document.createElement('p')
    emptyState.className = 'hidden rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500'
    root.appendChild(emptyState)

    const results = document.createElement('div')
    results.className = 'max-h-[60vh] overflow-y-auto overflow-x-hidden pr-1'
    root.appendChild(results)

    return {
        root,
        searchInput,
        emptyState,
        results,
    }
}

/**
 * Creates a variable div
 * @param label the label
 * @param icon the icon
 * @returns the variable div
 */
function createVariableDiv(
    sourceLabel:string,
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

    const sourceBadge = document.createElement('span')
    sourceBadge.className = 'inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-slate-600'
    sourceBadge.textContent = sourceLabel

    const titleRow = document.createElement('div')
    titleRow.className = 'flex items-center justify-between gap-2'
    titleRow.appendChild(labelDiv)
    titleRow.appendChild(sourceBadge)

    const descriptionDiv = document.createElement('div')
    descriptionDiv.className = 'text-xs text-gray-500'
    descriptionDiv.textContent = description

    const labelWrapper = document.createElement('div')
    labelWrapper.className = 'flex flex-col'
    labelWrapper.appendChild(titleRow)
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
        button.dataset.variableMethodButton = 'true'
        button.dataset.methodId = injectionMethod.id
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

function renderVariableEntryList(
    container:HTMLDivElement,
    entries:VariablePickerEntry[],
    onSelect:(entry:VariablePickerEntry, methodId:string)=>void,
    onRemoveFreeVariable?:(slug:string)=>void,
) : VariablePickerItem[] {
    container.innerHTML = ''

    return entries.map((entry)=>{
        const item = createVariableDiv(
            entry.sourceLabel,
            entry.label,
            entry.icon,
            entry.description,
            entry.injectionMethods,
            (methodId) => onSelect(entry, methodId),
            entry.isFreeVariable && onRemoveFreeVariable ? () => onRemoveFreeVariable(entry.token) : undefined,
        )

        container.appendChild(item)
        return { entry, element: item }
    })
}

export class DocumentTemplateBuilder extends BaseComponent {
    private editor: BloomerpTextEditor;
    private pageContainer: HTMLDivElement;
    private pageContentSection:HTMLDivElement;
    private pageHeaderSection:HTMLDivElement;
    private currentPageSize: 'A4' | 'A3' | 'Letter' = 'A4';
    private currentPageOrientation: 'landscape' | 'portrait' = 'portrait';
    
    private freeVariables: FreeVariable[] = [];
    private modelVariableEntries: VariablePickerEntry[] = [];
    private freeVariableField: CodeEditorWidget|null = null;
    private freeVariableInput: HTMLTextAreaElement|null = null;
    private sidebarVariableSearchInput: HTMLInputElement|null = null;
    private variablePickerItems: VariablePickerItem[] = [];
    private variablePickerActiveIndex: number = -1;
    private variablePickerActiveMethodIndex: number = 0;

    private documentTemplateId: string|null = null;
    private stylingRequestSequence: number = 0;

    

    // Preview URL
    private previewUrl: string|null = null;


    public initialize(): void {
        // Get dataset
        this.documentTemplateId = this.element.dataset.documentTemplateId || null;
        this.previewUrl = this.element.dataset.previewUrl || null;

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

        // Apply custom styling
        const customStylingField = this.getFieldComponent<CodeEditorWidget>('custom_styling');


        // Apply style sets
        const styleSetsField = this.getFieldComponent<ForeignFieldWidget>('style_sets');
        const applyTemplateStyling = () => {
            const customStyling = customStylingField?.getValue() as string | null;
            const styleSetIds = this.normalizeStyleIds(styleSetsField?.getValue() as string[] | string | null | undefined);
            this.applyPageStyling(styleSetIds, customStyling || '');
        }
        applyTemplateStyling()
        customStylingField?.element.addEventListener('bloomerp:widget-change', applyTemplateStyling)
        styleSetsField?.element.addEventListener('bloomerp:widget-change', applyTemplateStyling)


        // Render content types
        const contentTypes = getComponent(this.getFormField('content_types')) as ForeignFieldWidget;
        this.renderContentTypes(contentTypes.getValue() as string[])
        contentTypes.element.addEventListener('bloomerp:widget-change', ()=>{this.renderContentTypes(contentTypes.getValue() as string[])})

        // Free variables
        this.freeVariableInput = this.getFormField('free_variables') as HTMLTextAreaElement|null;
        const freeVariableComponent = this.freeVariableInput?.closest('[bloomerp-component="code-editor-widget"]') as HTMLElement|null;
        this.freeVariableField = freeVariableComponent ? getComponent(freeVariableComponent) as CodeEditorWidget : null;
        this.freeVariables = this.readFreeVariables();
        this.syncFreeVariablesInput();
        this.sidebarVariableSearchInput = this.element.querySelector('#variable-search-input') as HTMLInputElement | null;
        this.sidebarVariableSearchInput?.addEventListener('input', ()=>{
            this.renderSidebarVariables()
        })
        this.renderSidebarVariables();
        
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

        // Add command
        this.editor.registerAction(
            {
                label: "Add variable",
                icon: "fa-solid fa-plus",
                handler: (editor) => {
                    this.openVariablePicker()
                }
            },
            'variables',
            true
        )

        this.editor.registerAction(
            {
                label: "Preview document",
                icon: "fa-solid fa-eye",
                handler: (editor) => {
                    const modal = getGeneralModal()
                    modal.setSize('full')
                    modal.setTitle('Document preview')
                    
                    htmx.ajax(
                        'get',
                        this.previewUrl,
                        {
                            target: modal.getBodyElement(),
                            swap: 'innerHTML'
                        }
                    ).then(()=>{
                        modal.open()}
                    )
                    
                }
            },
            'preview',
            true,
            false
        )

        this.editor.registerAction(
            {
                label: "Save",
                icon: "fa-solid fa-floppy-disk",
                handler: () => {
                    this.saveDocumentTemplate(true)
                }
            },
            'save_document_template',
            true,
            false
        )

        // Initialize autosave
        this.initializeAutosave()
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
    private applyPageStyling(styleIds:string[]|null, customStyling:string = '') : void{
        const sdk = getSdk();
        const requestSequence = ++this.stylingRequestSequence;
        const normalizedStyleIds = this.normalizeStyleIds(styleIds);

        Promise.all(
            normalizedStyleIds.map((styleId)=>sdk.documentTemplateStylings.retrieve(styleId))
        )
            .then((styleSets)=>{
                if (requestSequence !== this.stylingRequestSequence) {return}

                const styling = [
                    customStyling,
                    ...styleSets.map((styleSet)=>styleSet.styling || ''),
                ]
                    .map((style)=>style.trim())
                    .filter(Boolean)
                    .join('\n\n')

                this.editor.setStyling(styling)
            })
            .catch((error)=>{
                console.error('Error applying document template styling:', error)
                if (requestSequence === this.stylingRequestSequence) {
                    this.editor.setStyling(customStyling)
                }
            })
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

    private getFieldComponent<T>(id:string) : T|null {
        const field = this.getFormField(id) as HTMLElement | null
        const componentElement = field?.closest('[bloomerp-component]') as HTMLElement | null
        if (!componentElement) {return null}
        return getComponent(componentElement) as T|null
    }

    private normalizeStyleIds(value:string[]|string|null|undefined) : string[] {
        if (!value) {return []}
        const values = Array.isArray(value) ? value : [value]
        return values.map((item)=>String(item).trim()).filter(Boolean)
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
        this.renderSidebarVariables()
        this.scheduleAutosave()
    }

    /**
     * Renders the combined sidebar variables
     */
    private renderSidebarVariables() {
        const variableResults = this.element.querySelector('#variable-results') as HTMLDivElement | null
        const emptyState = this.element.querySelector('#variable-results-empty') as HTMLParagraphElement | null
        if (!variableResults || !emptyState) {return}

        const query = this.sidebarVariableSearchInput?.value || ''
        const entries = this.getVariableEntries(query)
        renderVariableEntryList(
            variableResults,
            entries,
            (entry, methodId) => this.insertVariable(entry.token, methodId, entry.isFreeVariable),
            (slug) => this.removeFreeVariable(slug),
        )

        const hasQuery = Boolean(query.trim())
        emptyState.textContent = hasQuery
            ? `No variables match "${query.trim()}".`
            : 'No variables are available.'
        emptyState.classList.toggle('hidden', entries.length > 0)
    }

    /**
     * Renders the model variables from the data returned by the catalog endpoint
     * @param html 
     */
    private renderModelVariables(html:string) {
        this.modelVariableEntries = []

        const template = document.createElement('template')
        template.innerHTML = html

        template.content.querySelectorAll('[data-model-variable]').forEach((element)=>{
            const variableElement = element as HTMLElement
            const entry = createModelVariablePickerEntry(variableElement)
            if (!entry) {return}
            this.modelVariableEntries.push(entry)
        })

        this.renderSidebarVariables()
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
        this.renderSidebarVariables()
        this.scheduleAutosave()
    }
    
    /**
     * AUTOSAVE LOGIC
     */
    private autosaveTimer: number|null = null;
    private autosaveInFlight: boolean = false;
    private autosaveQueued: boolean = false;
    private lastAutosavePayload: Record<string, unknown>|null = null;

    private initializeAutosave() {
        if (!this.documentTemplateId) {return}

        this.lastAutosavePayload = this.getAutosavePayload()
        this.editor.element.addEventListener('bloomerp:widget-change', ()=>this.scheduleAutosave())

        const autosaveFields = [
            'name',
            'content_types',
            'page_orientation',
            'page_size',
            'page_margin',
            'include_page_numbers',
            'template_header',
            'custom_styling',
            'style_sets',
            'free_variables',
            'template',
        ]

        autosaveFields.forEach((fieldId)=>{
            const field = this.getFormField(fieldId) as HTMLElement|null
            console.log(fieldId, field)
            const component = field?.closest('[bloomerp-component]') as HTMLElement|null
            const eventTarget = component || field
            eventTarget?.addEventListener('change', ()=>this.scheduleAutosave())
            eventTarget?.addEventListener('bloomerp:widget-change', ()=>this.scheduleAutosave())
        })
    }

    private scheduleAutosave() {
        if (!this.documentTemplateId) {return}
        if (this.autosaveTimer) {
            window.clearTimeout(this.autosaveTimer)
        }
        this.autosaveTimer = window.setTimeout(()=>this.flushAutosave(), AUTO_SAVE_INTERVAL_MS)
    }

    private flushAutosave() {
        this.saveDocumentTemplate(false)
    }

    private saveDocumentTemplate(showFeedback:boolean = false) {
        if (!this.documentTemplateId) {return}

        if (this.autosaveTimer) {
            window.clearTimeout(this.autosaveTimer)
            this.autosaveTimer = null
        }

        const payload = this.getAutosavePayload()
        const changedPayload = this.getChangedAutosavePayload(payload)
        if (!Object.keys(changedPayload).length) {
            if (showFeedback) {
                showMessage('Document template is already saved.', MessageType.INFO)
            }
            return
        }

        if (this.autosaveInFlight) {
            this.autosaveQueued = true
            if (showFeedback) {
                showMessage('Save already in progress. Your latest changes will be saved next.', MessageType.INFO)
            }
            return
        }

        this.autosaveInFlight = true
        getSdk().documentTemplates.partialUpdate(this.documentTemplateId, changedPayload as any)
            .then(()=>{
                this.lastAutosavePayload = payload
                if (showFeedback) {
                    showMessage('Document template saved.', MessageType.SUCCESS)
                }
            })
            .catch((error)=>{
                console.error('Error auto-saving document template:', error)
                if (showFeedback) {
                    showMessage('Could not save document template. Please try again.', MessageType.ERROR)
                }
            })
            .finally(()=>{
                this.autosaveInFlight = false
                if (this.autosaveQueued) {
                    this.autosaveQueued = false
                    this.scheduleAutosave()
                }
            })
    }

    private getAutosavePayload() : Record<string, unknown> {
        return {
            name: this.getFieldValue('name'),
            template: this.editor.getValue(),
            content_types: this.normalizeStyleIds(this.getFieldValue('content_types') as string[]|string|null|undefined),
            page_orientation: this.getFieldValue('page_orientation'),
            page_size: this.getFieldValue('page_size'),
            page_margin: Number.parseFloat(String(this.getFieldValue('page_margin') || 0)),
            include_page_numbers: Boolean(this.getFieldValue('include_page_numbers')),
            template_header: this.getFieldValue('template_header') || null,
            custom_styling: this.getFieldValue('custom_styling') || '',
            style_sets: this.normalizeStyleIds(this.getFieldValue('style_sets') as string[]|string|null|undefined),
            free_variables: this.freeVariables.map((variable)=>({
                slug: variable.slug,
                label: variable.label,
                type: variable.type,
                required: variable.required,
                choices: variable.choices,
            })),
        }
    }

    private getFieldValue(id:string) : unknown {
        const field = this.getFormField(id) as HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement|null
        const componentElement = field?.closest('[bloomerp-component]') as HTMLElement|null
        const component = componentElement ? getComponent(componentElement) as { getValue?: () => unknown }|null : null
        if (component?.getValue) {return component.getValue()}
        if (field?.type === 'checkbox') {return (field as HTMLInputElement).checked}
        return field?.value || ''
    }

    private getChangedAutosavePayload(payload: Record<string, unknown>) : Record<string, unknown> {
        if (!this.lastAutosavePayload) {return payload}

        return Object.fromEntries(
            Object.entries(payload).filter(([key, value])=>(
                JSON.stringify(value) !== JSON.stringify(this.lastAutosavePayload?.[key])
            ))
        )
    }

    private getVariableEntries(query:string = '') {
        return [
            ...this.modelVariableEntries,
            ...this.freeVariables.map((variable)=>createFreeVariablePickerEntry(variable)),
        ]
            .filter((entry)=>matchesVariablePickerEntry(entry, query))
    }

    private openVariablePicker() {
        const modal = getModal('add-variable-modal')
        const modalBody = modal.getBodyElement()
        if (!modalBody) {return}

        modal.resetToDefaults()
        modal.setSize('lg')
        modal.setTitle('Add variable')
        modalBody.innerHTML = ''

        const layout = createVariablePickerLayout()
        modalBody.appendChild(layout.root)

        this.variablePickerActiveIndex = -1
        this.variablePickerActiveMethodIndex = 0
        this.renderVariablePickerResults(layout.results, layout.emptyState, '')

        layout.searchInput.addEventListener('input', () => {
            this.renderVariablePickerResults(layout.results, layout.emptyState, layout.searchInput.value)
        })

        layout.searchInput.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'ArrowDown') {
                event.preventDefault()
                this.moveVariablePickerSelection(1)
                return
            }

            if (event.key === 'ArrowUp') {
                event.preventDefault()
                this.moveVariablePickerSelection(-1)
                return
            }

            if (event.key === 'ArrowRight') {
                event.preventDefault()
                this.moveVariablePickerMethodSelection(1)
                return
            }

            if (event.key === 'ArrowLeft') {
                event.preventDefault()
                this.moveVariablePickerMethodSelection(-1)
                return
            }

            if (event.key === 'Enter') {
                const activeItem = this.getActiveVariablePickerItem()
                const activeMethodId = this.getActiveVariablePickerMethodId(activeItem)
                if (!activeItem || !activeMethodId) {return}

                event.preventDefault()
                this.insertVariableFromPicker(activeItem.entry, activeMethodId)
            }
        })

        modal.open()
        window.setTimeout(() => {
            layout.searchInput.focus()
        }, 80)
    }

    private renderVariablePickerResults(
        container:HTMLDivElement,
        emptyState:HTMLParagraphElement,
        query:string,
    ) {
        this.variablePickerItems = renderVariableEntryList(
            container,
            this.getVariableEntries(query),
            (entry, methodId) => this.insertVariableFromPicker(entry, methodId),
        )

        this.variablePickerItems.forEach((item)=>{
            item.element.classList.add('cursor-pointer', 'transition-colors')
            item.element.dataset.variablePickerId = item.entry.id
            item.element.addEventListener('click', (event: MouseEvent) => {
                const target = event.target as HTMLElement | null
                if (target?.closest('button')) {return}

                const defaultMethod = item.entry.injectionMethods[0]?.id
                if (!defaultMethod) {return}
                this.insertVariableFromPicker(item.entry, defaultMethod)
            })
        })

        const hasQuery = Boolean(query.trim())
        emptyState.textContent = hasQuery
            ? `No variables match "${query.trim()}".`
            : 'No variables are available.'
        emptyState.classList.toggle('hidden', this.variablePickerItems.length > 0)

        this.variablePickerActiveIndex = this.variablePickerItems.length > 0 ? 0 : -1
        this.variablePickerActiveMethodIndex = 0
        this.updateVariablePickerActiveState(this.variablePickerItems)
    }

    private moveVariablePickerSelection(delta:1|-1) {
        const visibleItems = this.getVisibleVariablePickerItems()
        if (!visibleItems.length) {return}

        this.variablePickerActiveIndex = getWrappedIndex(this.variablePickerActiveIndex, delta, visibleItems.length)
        this.variablePickerActiveMethodIndex = 0
        this.updateVariablePickerActiveState(visibleItems)

        const activeItem = this.getActiveVariablePickerItem()
        activeItem?.element.scrollIntoView({ block: 'nearest' })
    }

    private moveVariablePickerMethodSelection(delta:1|-1) {
        const activeItem = this.getActiveVariablePickerItem()
        if (!activeItem) {return}

        const methodButtons = this.getVariablePickerMethodButtons(activeItem)
        if (!methodButtons.length) {return}

        this.variablePickerActiveMethodIndex = getWrappedIndex(
            this.variablePickerActiveMethodIndex,
            delta,
            methodButtons.length,
        )
        this.updateVariablePickerActiveState(this.getVisibleVariablePickerItems())
        methodButtons[this.variablePickerActiveMethodIndex]?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }

    private updateVariablePickerActiveState(visibleItems:VariablePickerItem[]) {
        this.variablePickerItems.forEach((item)=>{
            item.element.classList.remove('border-primary-300', 'bg-primary-50', 'ring-1', 'ring-primary-200')
            this.getVariablePickerMethodButtons(item).forEach((button)=>{
                button.classList.remove('ring-2', 'ring-primary-300', 'bg-primary/16')
            })
        })

        if (visibleItems.length === 0) {return}

        const nextIndex = this.variablePickerActiveIndex >= 0 ? this.variablePickerActiveIndex : 0
        this.variablePickerActiveIndex = Math.min(nextIndex, visibleItems.length - 1)

        const activeItem = visibleItems[this.variablePickerActiveIndex]
        activeItem.element.classList.add('border-primary-300', 'bg-primary-50', 'ring-1', 'ring-primary-200')

        const methodButtons = this.getVariablePickerMethodButtons(activeItem)
        if (!methodButtons.length) {return}

        this.variablePickerActiveMethodIndex = Math.min(this.variablePickerActiveMethodIndex, methodButtons.length - 1)
        const activeMethodButton = methodButtons[this.variablePickerActiveMethodIndex]
        activeMethodButton.classList.add('ring-2', 'ring-primary-300', 'bg-primary/16')
    }

    private getVisibleVariablePickerItems() {
        return this.variablePickerItems.filter((item)=>!item.element.classList.contains('hidden'))
    }

    private getActiveVariablePickerItem() {
        const visibleItems = this.getVisibleVariablePickerItems()
        if (this.variablePickerActiveIndex < 0 || this.variablePickerActiveIndex >= visibleItems.length) {
            return null
        }
        return visibleItems[this.variablePickerActiveIndex]
    }

    private getVariablePickerMethodButtons(item:VariablePickerItem) {
        return Array.from(
            item.element.querySelectorAll<HTMLButtonElement>('[data-variable-method-button="true"]')
        )
    }

    private getActiveVariablePickerMethodId(item:VariablePickerItem | null) {
        if (!item) {return null}

        const methodButtons = this.getVariablePickerMethodButtons(item)
        if (!methodButtons.length) {return null}

        const nextIndex = Math.min(this.variablePickerActiveMethodIndex, methodButtons.length - 1)
        this.variablePickerActiveMethodIndex = nextIndex
        return methodButtons[nextIndex].dataset.methodId || null
    }

    private insertVariableFromPicker(entry:VariablePickerEntry, methodId:string) {
        this.insertVariable(entry.token, methodId, entry.isFreeVariable)
        getModal('add-variable-modal').close()
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

        this.removeSlashTriggerWord()
        this.editor.insertNode(() => $createTextNode(snippet))
    }

    private removeSlashTriggerWord() {
        this.editor.editor?.update(() => {
            const currentWord = getCurrentWordFromSelection()
            if (currentWord[0] === '/') {
                removeTextFromCurrentSelection(currentWord)
            }
        })
    }

}
