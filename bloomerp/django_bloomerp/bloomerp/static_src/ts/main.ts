/**
 * Bloomerp Main TypeScript Entry Point
 * 
 * This file serves as the main entry point for all TypeScript modules.
 * It sets up HTMX event listeners to handle dynamically loaded content
 * and initializes modules as needed.
 */
import 'htmx.org';

import { registerComponent, setupComponentAutoInit } from './components/BaseComponent';
import { Sidebar } from './components/Sidebar';
import { DataTable } from './components/data_view_components/DataTable'
import { DataTableCell } from './components/data_view_components/DataTable'
import { DataViewContainer } from './components/data_view_components/DataViewContainer';
import { KanbanBoard } from './components/data_view_components/KanbanBoard';
import { KanbanCard } from './components/data_view_components/KanbanBoard';

// Register components here
registerComponent('sidebar', Sidebar);

// Dataview component
registerComponent('dataview-container', DataViewContainer);

// Datatable
registerComponent('datatable', DataTable);
registerComponent('datatable-cell', DataTableCell);

// Kanban
registerComponent('kanban-board', KanbanBoard);
registerComponent('kanban-card', KanbanCard);

// Auto init comonents
setupComponentAutoInit();