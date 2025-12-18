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
import { DataTable } from './components/DataTable'
import { DataTableCell } from './components/DataTableCell'
import { DataView } from './components/DataView';
import { KanbanBoard } from './components/KanbanBoard';
import { KanbanCard } from './components/KanbanCard';

// Register components here
registerComponent('sidebar', Sidebar);

// Dataview component
registerComponent('dataview', DataView);

// Datatable
registerComponent('datatable', DataTable);
registerComponent('datatable-cell', DataTableCell);

// Kanban
registerComponent('kanban-board', KanbanBoard);
registerComponent('kanban-card', KanbanCard);

// Auto init comonents
setupComponentAutoInit();