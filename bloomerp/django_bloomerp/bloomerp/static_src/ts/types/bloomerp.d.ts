/**
 * Type definitions for Bloomerp application
 */

export interface DataViewConfig {
  containerId: string;
  viewType?: string;
  url?: string;
  enableContextMenu?: boolean;
}

export interface DataViewContextTrigger extends HTMLElement {
  dataset: {
    dropdown?: string;
    column?: string;
    value?: string;
    objectId?: string;
    contextMenuFilterValue?: string;
    applicationFieldId?:string;
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
