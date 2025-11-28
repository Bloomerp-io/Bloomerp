/**
 * Views Module Index
 * 
 * Exports all view types and the base interface.
 */

export { BaseView, NAVIGATION_KEYS } from './base';
export type { IView, ViewConfig } from './base';
export { TableView } from './table';
export { KanbanView } from './kanban';
export { CalendarView } from './calendar';
