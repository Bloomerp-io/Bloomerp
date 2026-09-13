

type FilterCondition = {
    fieldPath: string
    expression: string
    value: any
}

type Filter = {
    connector: 'AND' | 'OR'
    conditions: FilterCondition[]
}


type LookupDefinition = {
    id:string
    label:string
    nested:boolean
}