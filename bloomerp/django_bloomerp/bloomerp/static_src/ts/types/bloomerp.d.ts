/**
 * Type definitions for Bloomerp application
 */

export interface DataTableConfig {
  tableId: string;
  url?: string;
  enableContextMenu?: boolean;
}

export interface DataTableCell extends HTMLTableCellElement {
  dataset: {
    dropdown?: string;
    column?: string;
    value?: string;
    objectId?: string;
    editable?: string;
    inputType?: string;
    contextMenuFilterValue?: string;
  };
}

export interface MessageOptions {
  message: string;
  type: 'success' | 'info' | 'warning' | 'error';
  duration?: number;
}

export interface ContextMenuPosition {
  x: number;
  y: number;
}
