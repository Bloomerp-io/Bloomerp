/**
 * HTMX type definitions for TypeScript
 * Based on htmx.org v2.0+
 */

declare global {
  interface Window {
    htmx: HtmxApi;
  }

  interface HtmxApi {
    ajax(method: string, url: string, selector: string | HtmxAjaxOptions): void;
    config: HtmxConfig;
    on(event: string, handler: (evt: CustomEvent) => void): void;
    on(target: EventTarget, event: string, handler: (evt: CustomEvent) => void): void;
    off(event: string, handler: (evt: CustomEvent) => void): void;
    off(target: EventTarget, event: string, handler: (evt: CustomEvent) => void): void;
    trigger(element: Element, event: string, detail?: any): void;
    find(selector: string): Element | null;
    findAll(selector: string): NodeListOf<Element>;
    process(element: Element): void;
    remove(element: Element): void;
    addClass(element: Element, className: string): void;
    removeClass(element: Element, className: string): void;
    toggleClass(element: Element, className: string): void;
    takeClass(element: Element, className: string): void;
    closest(element: Element, selector: string): Element | null;
    values(element: Element, requestType?: string): Record<string, any>;
  }

  interface HtmxConfig {
    historyEnabled: boolean;
    historyCacheSize: number;
    refreshOnHistoryMiss: boolean;
    defaultSwapStyle: string;
    defaultSwapDelay: number;
    defaultSettleDelay: number;
    includeIndicatorStyles: boolean;
    indicatorClass: string;
    requestClass: string;
    addedClass: string;
    settlingClass: string;
    swappingClass: string;
    allowEval: boolean;
    allowScriptTags: boolean;
    inlineScriptNonce: string;
    useTemplateFragments: boolean;
    wsReconnectDelay: string;
    wsBinaryType: string;
    disableSelector: string;
    timeout: number;
    scrollBehavior: string;
    defaultFocusScroll: boolean;
    getCacheBusterParam: boolean;
    globalViewTransitions: boolean;
    methodsThatUseUrlParams: string[];
    selfRequestsOnly: boolean;
    ignoreTitle: boolean;
    scrollIntoViewOnBoost: boolean;
    triggerSpecsCache: any;
  }

  interface HtmxAjaxOptions {
    target?: string;
    swap?: string;
    values?: Record<string, any>;
    headers?: Record<string, string>;
  }

  interface HtmxEvent extends CustomEvent {
    detail: {
      elt?: Element;
      target?: Element;
      xhr?: XMLHttpRequest;
      requestConfig?: any;
      pathInfo?: any;
      shouldSwap?: boolean;
      serverResponse?: any;
      isError?: boolean;
      etc?: any;
    };
  }
}

export {};
