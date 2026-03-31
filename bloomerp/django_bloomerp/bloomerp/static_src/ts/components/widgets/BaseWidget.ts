import BaseComponent from "../BaseComponent";

export type BaseWidgetChangeDetail<TValue = unknown> = {
    widget: BaseWidget;
    value: TValue;
};

export type BaseWidgetSerializableState = {
    value: unknown;
};

/**
 * The base widget needs to be inherited by all custom widgets (defined by components)
 * so that we can add custom events on them. The reason for this is that
 * we need to be able to identify change events on these widgets
 */
export abstract class BaseWidget extends BaseComponent {
    public static readonly changeEventName = "bloomerp:widget-change";

    public onChange(): void {
        if (!this.element) return;

        const value = this.getValue();

        console.log("Widget changed:", this.constructor.name, value);

        this.element.dispatchEvent(
            new CustomEvent<BaseWidgetChangeDetail>(BaseWidget.changeEventName, {
                bubbles: true,
                detail: {
                    widget: this,
                    value,
                },
            }),
        );
    }

    abstract getValue(): unknown;
    abstract setValue(value: unknown, emitChange?: boolean): void;

    public getSerializableState(): BaseWidgetSerializableState {
        return {
            value: this.getValue(),
        };
    }

    public setSerializableState(state: BaseWidgetSerializableState, emitChange: boolean = false): void {
        this.setValue(state.value, emitChange);
    }
}
