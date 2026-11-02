// This public entry and main.ts share the same module and component registries.
export {
    default as BaseComponent,
    registerComponent,
    getComponent,
    initComponents,
    componentIdentifier,
} from './components/BaseComponent';
