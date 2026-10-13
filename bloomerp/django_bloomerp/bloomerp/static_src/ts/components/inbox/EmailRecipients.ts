import { getSdk } from "../../sdk/getSdk";
import { t as _ } from "../../utils/i18n";

/** Split pasted recipient lists without breaking quoted display names. */
function splitRecipients(value: string): string[] {
    const parts: string[] = [];
    let current = "";
    let quoted = false;
    for (const character of value) {
        if (character === '"') quoted = !quoted;
        if (!quoted && [",", ";", "\n", "\r"].includes(character)) {
            if (current.trim()) parts.push(current.trim());
            current = "";
        } else current += character;
    }
    if (current.trim()) parts.push(current.trim());
    return parts;
}

/** Own one chip-based recipient field while preserving its submitted form value. */
export class EmailRecipients {
    private readonly container: HTMLDivElement;
    private readonly chips: HTMLDivElement;
    private readonly entry: HTMLInputElement;
    private readonly source: HTMLInputElement;
    private values: string[];
    private readonly suggestions: HTMLDivElement;
    private readonly searchUrl?: string;
    private searchTimer?: ReturnType<typeof setTimeout>;
    private searchRequest?: AbortController;
    private activeSuggestion = -1;

    /** Replace a plain input with keyboard-accessible chips and a typing area. */
    public constructor(source: HTMLInputElement, signal: AbortSignal, searchUrl?: string) {
        this.source = source;
        this.searchUrl = searchUrl;
        this.values = splitRecipients(source.value);
        this.container = document.createElement("div");
        this.container.className = "relative flex min-w-0 flex-wrap items-center gap-1.5 py-2";
        this.chips = document.createElement("div");
        this.chips.className = "contents";
        this.entry = document.createElement("input");
        this.entry.type = "text";
        this.entry.className = "min-w-24 flex-1 border-0 bg-transparent px-0 py-1 text-sm placeholder:text-gray-400 focus:ring-0";
        this.entry.setAttribute("aria-label", source.getAttribute("aria-label") ?? source.name);
        this.entry.autocomplete = "off";
        this.suggestions = document.createElement("div");
        this.suggestions.id = "email-suggestions-" + crypto.randomUUID();
        this.suggestions.className = "absolute left-0 top-full z-50 max-h-60 w-full overflow-y-auto rounded-md border border-gray-200 bg-white p-1 shadow-lg";
        this.suggestions.hidden = true;
        this.suggestions.setAttribute("role", "listbox");
        this.suggestions.setAttribute("aria-label", _("Suggested email addresses"));
        this.entry.setAttribute("role", "combobox");
        this.entry.setAttribute("aria-autocomplete", "list");
        this.entry.setAttribute("aria-controls", this.suggestions.id);
        this.entry.setAttribute("aria-expanded", "false");
        this.suggestions.addEventListener("mousedown", this.keepInputFocus, { signal });
        this.suggestions.addEventListener("click", this.onSuggestionClick, { signal });
        signal.addEventListener("abort", this.closeSuggestions, { once: true });
        this.entry.addEventListener("keydown", this.onKeyDown, { signal });
        this.entry.addEventListener("blur", this.onBlur, { signal });
        this.entry.addEventListener("input", this.onInput, { signal });
        source.before(this.container);
        source.type = "hidden";
        this.container.append(source, this.chips, this.entry, this.suggestions);
        this.render();
        this.sync();
    }

    /** Extract a mailbox address from an optional pasted display-name wrapper. */
    private address(value: string): string {
        return value.match(/<([^<>]+)>\s*$/)?.[1]?.trim() ?? value.trim();
    }

    /** Use browser email validation for each committed mailbox. */
    private valid(value: string): boolean {
        const probe = document.createElement("input");
        probe.type = "email";
        probe.value = this.address(value);
        return probe.value.length > 0 && probe.checkValidity();
    }

    /** Preserve unfinished text in autosave without requiring a committed chip. */
    private sync(): void {
        this.source.value = [...this.values, this.entry.value.trim()].filter(Boolean).join(", ");
        this.entry.placeholder = this.values.length ? "" : "name@example.com";
    }

    /** Build safe, removable chip labels and mark invalid addresses visibly. */
    private render(): void {
        this.chips.replaceChildren();
        for (const value of this.values) {
            const chip = document.createElement("span");
            chip.dataset.recipientChip = value;
            chip.className = "inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-1 text-sm "
                + (this.valid(value) ? "border-gray-200 bg-base text-gray-950" : "border-danger-dark bg-danger-light/10 text-danger-dark");
            const text = document.createElement("span");
            text.className = "truncate";
            text.textContent = value;
            chip.title = value;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "shrink-0 rounded-full px-1 hover:bg-gray-200 focus:ring-2 focus:ring-primary";
            remove.setAttribute("aria-label", `${_("Remove recipient")}: ${value}`);
            remove.textContent = "×";
            remove.addEventListener("click", this.onRemove);
            chip.append(text, remove);
            this.chips.append(chip);
        }
    }

    /** Commit typed recipients, deduplicate addresses, and notify autosave. */
    public commit(): void {
        this.closeSuggestions();
        if (!this.entry.value.trim()) return;
        for (const value of splitRecipients(this.entry.value)) {
            const address = this.address(value).toLowerCase();
            if (!this.values.some(this.matchesAddress.bind(this, address))) this.values.push(value);
        }
        this.entry.value = "";
        this.entry.setCustomValidity("");
        this.render();
        this.sync();
        this.source.dispatchEvent(new Event("change", { bubbles: true }));
    }

    /** Compare mailbox addresses independently from their display labels. */
    private matchesAddress(address: string, value: string): boolean {
        return this.address(value).toLowerCase() === address;
    }

    /** Require all chips to be valid before either composer submits. */
    public validate(): boolean {
        this.commit();
        const invalid = this.values.find(this.isInvalid.bind(this));
        this.entry.setCustomValidity(invalid ? _("Enter a valid email address or remove the invalid recipient.") : "");
        if (invalid) {
            this.container.closest("[data-cc-field], [data-bcc-field]")?.classList.remove("hidden");
            this.entry.reportValidity();
            this.entry.focus();
        }
        return !invalid;
    }

    /** Identify an invalid committed recipient for submission validation. */
    private isInvalid(value: string): boolean {
        return !this.valid(value);
    }

    /** Remove one selected chip and return keyboard focus to the typing area. */
    private onRemove = (event: MouseEvent): void => {
        const value = (event.currentTarget as HTMLElement).parentElement!.dataset.recipientChip!;
        this.values = this.values.filter(this.differsFrom.bind(this, value));
        this.entry.setCustomValidity("");
        this.render();
        this.sync();
        this.entry.focus();
        this.source.dispatchEvent(new Event("change", { bubbles: true }));
    };

    /** Keep recipients other than the one selected for removal. */
    private differsFrom(removed: string, value: string): boolean {
        return removed !== value;
    }

    /** Commit on delimiters and let Backspace reopen the last chip for editing. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.isComposing) return;
        if (!this.suggestions.hidden) {
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                this.closeSuggestions();
                return;
            }
            if (["ArrowDown", "ArrowUp"].includes(event.key)) {
                event.preventDefault();
                const count = this.suggestionOptions().length;
                if (!count) return;
                this.activeSuggestion = this.activeSuggestion < 0
                    ? (event.key === "ArrowDown" ? 0 : count - 1)
                    : (this.activeSuggestion + (event.key === "ArrowDown" ? 1 : -1) + count) % count;
                this.highlightSuggestion();
                return;
            }
            if (["Enter", "Tab"].includes(event.key) && this.activeSuggestion >= 0) {
                if (event.key === "Enter") event.preventDefault();
                this.selectSuggestion(this.suggestionOptions()[this.activeSuggestion]);
                return;
            }
        }
        if (event.key === "Enter") event.preventDefault();
        if (["Enter", ",", ";", "Tab"].includes(event.key) && this.entry.value.trim()) {
            if (event.key !== "Tab") event.preventDefault();
            this.commit();
        } else if (event.key === "Backspace" && !this.entry.value && this.values.length) {
            event.preventDefault();
            this.entry.value = this.values.pop()!;
            this.render();
            this.sync();
            this.source.dispatchEvent(new Event("change", { bubbles: true }));
        }
    };

    /** Keep the form snapshot current and tokenize complete pasted lists. */
    private onInput = (event: Event): void => {
        this.entry.setCustomValidity("");
        if (event instanceof InputEvent && event.isComposing) return;
        if (/[,;\n\r]/.test(this.entry.value) && splitRecipients(this.entry.value).length > 1) this.commit();
        else {
            this.sync();
            if (this.searchUrl && this.entry.value.trim().length >= 2) {
                this.showSuggestionsLoading();
                this.searchTimer = setTimeout(this.loadSuggestions, 200);
            } else this.closeSuggestions();
        }
    };

    /** Keep the dropdown visible and nonselectable while debounced results update. */
    private showSuggestionsLoading(): void {
        clearTimeout(this.searchTimer);
        this.searchRequest?.abort();
        if (!this.suggestions.hidden) {
            this.suggestions.style.minHeight = `${this.suggestions.getBoundingClientRect().height}px`;
        }
        this.activeSuggestion = -1;
        this.entry.removeAttribute("aria-activedescendant");
        const loading = document.createElement("div");
        loading.className = "flex items-center gap-2 px-3 py-2 text-sm text-gray-500";
        loading.setAttribute("role", "status");
        const spinner = document.createElement("i");
        spinner.className = "fa fa-spinner animate-spin motion-reduce:animate-none";
        spinner.setAttribute("aria-hidden", "true");
        loading.append(spinner, document.createTextNode(_("Searching email addresses…")));
        this.suggestions.replaceChildren(loading);
        this.suggestions.setAttribute("aria-busy", "true");
        this.suggestions.hidden = false;
        this.entry.setAttribute("aria-expanded", "true");
    }

    /** Cancel pending searches and dismiss suggestions without changing typed text. */
    private closeSuggestions = (): void => {
        clearTimeout(this.searchTimer);
        this.searchRequest?.abort();
        this.suggestions.hidden = true;
        this.suggestions.removeAttribute("aria-busy");
        this.suggestions.style.minHeight = "";
        this.suggestions.replaceChildren();
        this.activeSuggestion = -1;
        this.entry.setAttribute("aria-expanded", "false");
        this.entry.removeAttribute("aria-activedescendant");
    };

    /** Fetch bounded suggestions while ignoring stale responses and optional search failures. */
    private loadSuggestions = async (): Promise<void> => {
        const query = this.entry.value.trim();
        const controller = new AbortController();
        this.searchRequest = controller;
        try {
            const result = await getSdk().client.request<{ suggestions: { email: string; label: string }[] }>(
                this.searchUrl!, { query: { q: query }, signal: controller.signal },
            );
            if (controller.signal.aborted || this.entry.value.trim() !== query || document.activeElement !== this.entry) return;
            this.suggestions.replaceChildren();
            this.suggestions.removeAttribute("aria-busy");
            this.suggestions.style.minHeight = "";
            const groups = new Map<string, HTMLDivElement>();
            for (const suggestion of result.suggestions) {
                if (this.values.some(this.matchesAddress.bind(this, suggestion.email.toLowerCase()))) continue;
                let group = groups.get(suggestion.label);
                if (!group) {
                    group = document.createElement("div");
                    group.setAttribute("role", "group");
                    const heading = document.createElement("div");
                    heading.id = this.suggestions.id + "-group-" + groups.size;
                    heading.className = "border-b border-gray-200 px-3 py-2 text-xs font-medium text-gray-500";
                    heading.textContent = suggestion.label;
                    group.setAttribute("aria-labelledby", heading.id);
                    group.append(heading);
                    groups.set(suggestion.label, group);
                    this.suggestions.append(group);
                }
                const option = document.createElement("div");
                option.id = this.suggestions.id + "-" + this.suggestionOptions().length;
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");
                option.dataset.email = suggestion.email;
                option.className = "cursor-pointer rounded px-3 py-2 text-sm hover:bg-gray-100";
                option.textContent = suggestion.email;
                option.classList.add("truncate");
                option.title = suggestion.email;
                group.append(option);
            }
            this.suggestions.hidden = !this.suggestionOptions().length;
            this.entry.setAttribute("aria-expanded", String(!this.suggestions.hidden));
        } catch {
            if (!controller.signal.aborted && this.searchRequest === controller) this.closeSuggestions();
            // Suggestions are optional; manual entry remains available on search failures.
        }
    };

    /** Keep the input focused until a clicked suggestion has been committed. */
    private keepInputFocus = (event: MouseEvent): void => {
        event.preventDefault();
    };

    /** Commit an explicitly clicked suggestion. */
    private onSuggestionClick = (event: MouseEvent): void => {
        const option = (event.target as HTMLElement).closest<HTMLElement>("[data-email]");
        if (option) this.selectSuggestion(option);
    };

    /** Replace the unfinished query with the selected address and commit its chip. */
    private selectSuggestion(option: HTMLElement): void {
        this.entry.value = option.dataset.email!;
        this.commit();
    }

    /** Return selectable addresses in rendered order, excluding model dividers. */
    private suggestionOptions(): HTMLElement[] {
        return Array.from(this.suggestions.querySelectorAll<HTMLElement>('[role="option"]'));
    }

    /** Reflect keyboard navigation in both visual and assistive-technology selection. */
    private highlightSuggestion(): void {
        for (const [index, element] of this.suggestionOptions().entries()) {
            const selected = index === this.activeSuggestion;
            element.setAttribute("aria-selected", String(selected));
            element.classList.toggle("bg-gray-100", selected);
            if (selected) {
                this.entry.setAttribute("aria-activedescendant", element.id);
                element.scrollIntoView({ block: "nearest" });
            }
        }
    }

    /** Turn a completed address into a chip when focus leaves the input. */
    private onBlur = (): void => {
        this.commit();
    };
}
