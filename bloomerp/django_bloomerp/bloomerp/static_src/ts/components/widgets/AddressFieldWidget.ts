import { BaseWidget } from "./BaseWidget";

type AddressValue = {
    street_1: string;
    street_2: string;
    postal_code: string;
    city: string;
    state: string;
    country: string;
} | null;

const ADDRESS_COMPONENT_KEYS = [
    "street_1",
    "street_2",
    "postal_code",
    "city",
    "state",
    "country",
] as const;

type AddressComponentKey = (typeof ADDRESS_COMPONENT_KEYS)[number];

export default class AddressFieldWidget extends BaseWidget {
    private fields = new Map<AddressComponentKey, HTMLInputElement | HTMLSelectElement>();
    private boundOnFieldChange: ((event: Event) => void) | null = null;

    public initialize(): void {
        this.refreshFields();

        this.boundOnFieldChange = this.handleFieldChange.bind(this);
        this.element.addEventListener("input", this.boundOnFieldChange as EventListener);
        this.element.addEventListener("change", this.boundOnFieldChange as EventListener);
    }

    public destroy(): void {
        if (!this.boundOnFieldChange) return;

        this.element.removeEventListener("input", this.boundOnFieldChange as EventListener);
        this.element.removeEventListener("change", this.boundOnFieldChange as EventListener);

        this.boundOnFieldChange = null;
    }

    public onAfterSwap(): void {
        this.refreshFields();
    }

    private refreshFields(): void {
        this.fields.clear();

        ADDRESS_COMPONENT_KEYS.forEach((key) => {
            const field = this.element.querySelector<HTMLInputElement | HTMLSelectElement>(
                `[data-address-component="${key}"]`,
            );
            if (field) {
                this.fields.set(key, field);
            }
        });
    }

    private handleFieldChange(event: Event): void {
        
        const target = event.target as HTMLElement | null;
        if (!target?.closest("[data-address-component]")) {
            return;
        }
        this.refreshFields();
        this.onChange();
    }

    public getValue(): AddressValue {
        this.refreshFields();
        const value = {
            street_1: this.getFieldValue("street_1"),
            street_2: this.getFieldValue("street_2"),
            postal_code: this.getFieldValue("postal_code"),
            city: this.getFieldValue("city"),
            state: this.getFieldValue("state"),
            country: this.getFieldValue("country"),
        };

        return Object.values(value).some((item) => item.length > 0) ? value : null;
    }

    public setValue(value: unknown, emitChange: boolean = false): void {
        this.refreshFields();
        const previousValue = this.getValue();
        const normalized = this.normalizeValue(value);

        ADDRESS_COMPONENT_KEYS.forEach((key) => {
            const field = this.fields.get(key);
            if (!field) return;
            field.value = normalized?.[key] ?? "";
        });

        if (emitChange && !this.valuesEqual(previousValue, this.getValue())) {
            this.onChange();
        }
    }

    private getFieldValue(key: AddressComponentKey): string {
        return this.fields.get(key)?.value?.trim() ?? "";
    }

    private normalizeValue(value: unknown): AddressValue {
        if (!value || typeof value !== "object") {
            return null;
        }

        const record = value as Partial<Record<AddressComponentKey, unknown>>;
        const normalized = {
            street_1: this.normalizeFieldValue(record.street_1),
            street_2: this.normalizeFieldValue(record.street_2),
            postal_code: this.normalizeFieldValue(record.postal_code),
            city: this.normalizeFieldValue(record.city),
            state: this.normalizeFieldValue(record.state),
            country: this.normalizeFieldValue(record.country),
        };

        return Object.values(normalized).some((item) => item.length > 0) ? normalized : null;
    }

    private normalizeFieldValue(value: unknown): string {
        return typeof value === "string" ? value : "";
    }

    private valuesEqual(left: AddressValue, right: AddressValue): boolean {
        if (left === right) {
            return true;
        }

        if (!left || !right) {
            return false;
        }

        return ADDRESS_COMPONENT_KEYS.every((key) => left[key] === right[key]);
    }
}
