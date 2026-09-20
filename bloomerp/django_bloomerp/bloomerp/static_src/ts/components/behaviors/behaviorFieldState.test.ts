import assert from "node:assert/strict";
import test from "node:test";

import {
    applyBehaviorFieldState,
    captureBehaviorFieldState,
    restoreBehaviorFieldState,
} from "./behaviorFieldState.ts";

class TestClassList {
    private values = new Set<string>();

    /** Report whether the synthetic class list contains a token. */
    public contains(value: string): boolean {
        return this.values.has(value);
    }

    /** Toggle a synthetic class using the browser DOMTokenList contract. */
    public toggle(value: string, force?: boolean): boolean {
        const enabled = force ?? !this.values.has(value);
        if (enabled) this.values.add(value);
        else this.values.delete(value);
        return enabled;
    }
}

type TestElement = HTMLElement & {
    value: string;
};

/** Create the minimal HTMLElement surface needed by field-state helpers. */
function createElement(): TestElement {
    const attributes = new Map<string, string>();
    return {
        classList: new TestClassList(),
        inert: false,
        value: "submitted value",
        hasAttribute(name: string): boolean {
            return attributes.has(name);
        },
        getAttribute(name: string): string | null {
            return attributes.get(name) ?? null;
        },
        setAttribute(name: string, value: string): void {
            attributes.set(name, value);
        },
        removeAttribute(name: string): void {
            attributes.delete(name);
        },
        toggleAttribute(name: string, force?: boolean): boolean {
            const enabled = force ?? !attributes.has(name);
            if (enabled) attributes.set(name, "");
            else attributes.delete(name);
            return enabled;
        },
    } as unknown as TestElement;
}

test("explicit disabled state uses inert without disabling or changing submitted values", () => {
    const element = createElement();
    element.classList.toggle("hidden", true);
    applyBehaviorFieldState(element, { visible: null, disabled: true });

    assert.equal(element.inert, true);
    assert.equal(element.getAttribute("aria-disabled"), "true");
    assert.equal(element.hasAttribute("disabled"), false);
    assert.equal(element.value, "submitted value");
    assert.equal(element.classList.contains("hidden"), true);
});

test("visibility and disabled state apply independently and reset exactly", () => {
    const element = createElement();
    element.inert = true;
    element.setAttribute("aria-disabled", "mixed");
    const original = captureBehaviorFieldState(element);

    applyBehaviorFieldState(element, { visible: false, disabled: false });
    assert.equal(element.classList.contains("hidden"), true);
    assert.equal(element.inert, false);
    assert.equal(element.getAttribute("aria-disabled"), "false");

    restoreBehaviorFieldState(element, original);
    assert.equal(element.classList.contains("hidden"), false);
    assert.equal(element.inert, true);
    assert.equal(element.getAttribute("aria-disabled"), "mixed");
    assert.equal(element.getAttribute("aria-hidden"), null);
});

test("enable reverses interaction lock without changing current visibility", () => {
    const element = createElement();
    element.classList.toggle("hidden", true);

    applyBehaviorFieldState(element, { visible: null, disabled: true });
    applyBehaviorFieldState(element, { visible: null, disabled: false });

    assert.equal(element.inert, false);
    assert.equal(element.getAttribute("aria-disabled"), "false");
    assert.equal(element.classList.contains("hidden"), true);
    assert.equal(element.value, "submitted value");
});
