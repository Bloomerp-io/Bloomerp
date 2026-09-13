import BaseComponent from "../BaseComponent"

class FilterContainer extends BaseComponent {
    private scope : "workspace" | "model"
    private id : string
    private filterState:Filter[]
    
    private addBtn: HTMLButtonElement
    private level:number = 0 // The level of nesting

    public initialize() {
        this.scope = this.getDataAttribute('scope') as "workspace" | "model"
        this.id = this.getDataAttribute('scopeId')

        this.renderFilterFields()

    }

    renderFilterFields(fieldPath?:string, lookupId?:string) {

    }

    renderLookups() {

    }

    renderValueEditor() {

    }

    onLookupSelect() {
        const lookup = this.getSelectedLookup()

        if (lookup.nested) {
            this.level+=1
            
            this.renderFilterFields(
                this.buildFieldPath(),
                lookup.id
            )
            return
        }

        this.renderValueEditor()
    }

    getSelectedLookup() : LookupDefinition {
        // Get the lookup from the current field
    }

    onApply():{
        // Build the filter state

    }

    buildFieldPath() : str {

    }

}