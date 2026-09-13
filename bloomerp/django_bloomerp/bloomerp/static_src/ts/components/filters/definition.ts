export type FilterCondition = { field_path: string; lookup_id: string; value: unknown };
export type Filter = { connector: 'AND' | 'OR'; conditions: FilterCondition[] };
export type LookupDefinition = { id: string; label: string; nested: boolean };
export type FilterField = { field: string; label: string };
export type FieldGroup = { name: string; fields: FilterField[] };
export type FilterScope = { scope: 'model' | 'workspace'; id: string };

export function parseInitialFilters(json: string): Filter[] {
    const value: unknown = JSON.parse(json);
    if (!Array.isArray(value) || !value.every(group =>
        group && ['AND', 'OR'].includes(group.connector) && Array.isArray(group.conditions) &&
        group.conditions.every(condition => condition && typeof condition.field_path === 'string' &&
            typeof condition.lookup_id === 'string' && Object.prototype.hasOwnProperty.call(condition, 'value')),
    )) throw new Error('Invalid initial filters');
    return value;
}
